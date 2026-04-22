VMEC_IN  := parastell/examples/wout_vmec.nc
COILS_IN := parastell/examples/coils.example
PARA_DIR := parastell/examples/alphastell_full
OUT_DIR  := out

# Rust の vessel が一括出力する 6 層 (内側 → 外側)。
# chamber は parastell の plasma.step と概念的に対応 (ファイル名のみ別)。
LAYERS := chamber first_wall breeder back_wall shield vacuum_vessel

# magnet (コイル)
MAG_OUT := $(OUT_DIR)/magnet_set.step
MAG_REF := $(PARA_DIR)/magnet_set.step

.PHONY: run vessel \
        validate $(addprefix validate-,$(LAYERS)) \
        cut cut-first-wall \
        magnet magnet-generate magnet-validate \
        points points-save plasma showcase

run: vessel validate

# ============================================================
# vessel — 6 層 in-vessel build を一括生成
#   出力: $(OUT_DIR)/{chamber,first_wall,breeder,back_wall,shield,vacuum_vessel}.step
#   wall_s=1.08 を基準に mesh() + boolean_subtract で構築 (Solid::shell は使わない)。
# ============================================================
vessel:
	cargo run --release -- vessel --input $(VMEC_IN) --output $(OUT_DIR)/

# ============================================================
# validate — 各層を parastell 参照と体積比較
#   Rust chamber.step ↔ parastell plasma.step (最内領域は命名違いだが同じ体積)。
#   他 5 層はファイル名が一致。
#   tol=0.05 は s=1.08 外挿 + Planar 2D 法線近似に由来する数 % 程度のズレを許容。
# ============================================================
validate: $(addprefix validate-,$(LAYERS))

validate-chamber:
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/chamber.step $(PARA_DIR)/plasma.step

validate-first_wall:
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/first_wall.step $(PARA_DIR)/first_wall.step

validate-breeder:
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/breeder.step $(PARA_DIR)/breeder.step

validate-back_wall:
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/back_wall.step $(PARA_DIR)/back_wall.step

validate-shield:
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/shield.step $(PARA_DIR)/shield.step

validate-vacuum_vessel:
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/vacuum_vessel.step $(PARA_DIR)/vacuum_vessel.step

# ============================================================
# cut — first_wall を Z 軸まわりの扇形で切る
#   --start/-s, --end/-e は τ (= 2π) 単位の有理数。形式 (+|-)?\d+(/\d+)? のみ。
#   例: -s 0 -e 1/2 で半周、-s 0 -e 1/4 で nfp=4 の 1 周期分、-s -1/6 -e 1/6 で非対称。
#   --cut/-c (扇形内側を残す) と --union/-u (扇形を除去) は排他必須。
#   内部は line+arc+line の閉 wire を extrude した扇柱と boolean 演算する方式で、
#   旧 half-space 方式の div>=3 empty 問題は回避済み。
# ============================================================
cut: cut-first-wall

cut-first-wall: vessel
	cargo run --release -- cut --cut -i $(OUT_DIR)/first_wall.step -o $(OUT_DIR)/first_wall_half.step -s 0 -e 1/2

# ============================================================
# plasma — VMEC LCFS (s=1.0) を複数 (M, N) 解像度で B-spline STEP 化
#   index_rz 直接 (スプライン補間なし)、scale=1 (m) で生 VMEC 単位。
#   出力: out/plasma_M{m}_N{n}.step を pair リスト分。
#   phi=0/2π seam の Nyquist aliasing 依存性を viewer で並べて切り分ける。
# ============================================================
plasma:
	cargo run --release -- plasma --input $(VMEC_IN) --output $(OUT_DIR)/

# ============================================================
# points — $(OUT_DIR) 下の *.csv をすべて matplotlib 3D 散布で重ね表示
#   header 有無は自動判定、末尾 3 列を (x, y, z) として扱う。
#   vessel (*.csv) / magnet (magnet_set.csv) ともに m 単位で同スケール、
#   重ねて viewing してもそのまま整合する。
#   環境変数 VIEW="azim,elev,roll" / OUTPUT=path で起動時の視点 / 保存先を指定可能。
# ============================================================
points:
	uv run tools/view_points.py ./$(OUT_DIR)

# points-save — ヘッドレスで $(OUT_DIR)/points.png に保存 (make points を OUTPUT 付きで再帰呼び出し)
points-save:
	OUTPUT=$(OUT_DIR)/points.png $(MAKE) points

# ============================================================
# magnet — coils.example から長方形断面 sweep で magnet_set.step を生成 (m 単位)
# ============================================================
magnet:
	cargo run --release -- magnet --input $(COILS_IN) --output $(MAG_OUT)

# ============================================================
# showcase — 核融合炉の内部を覗かせる cutaway STEP (+ 同名 SVG) を生成
#   各層を --union (+X 中心の扇形を除去) で等角度に開き、内部を段階的に露出。
#   半スパンは i * τ/36 (i=0..6) の等間隔で、chamber=0 → magnet=τ/6 = 半スパンτ/6、
#   ウェッジ総角で chamber=0°, magnet_set=120° (τ/3) まで。
#
#     i=0  chamber       : 0                  (切らない、そのまま)
#     i=1  first_wall    : ±1/36 (= 10°、span 20°)
#     i=2  breeder       : ±1/18 (= 20°、span 40°)
#     i=3  back_wall     : ±1/12 (= 30°、span 60°)
#     i=4  shield        : ±1/9  (= 40°、span 80°)
#     i=5  vacuum_vessel : ±5/36 (= 50°、span 100°)
#     i=6  magnet (±1/6) : compound --input-magnet で in-memory、120°ウェッジ外の
#                          コイルだけ 40 色 rainbow (build_sector が色付け)
#
#   vessel 6 層は compound::run が hsv(i*0.2/N, 1, 1) の穏やかな gradient で着色。
#   extras (magnet) は build_sector の rainbow をそのまま preserve。
#   同名 out/showcase.svg も自動生成 (-X 方向投影、隠線 + shading)。
# ============================================================
SHOWCASE_TMP := $(OUT_DIR)/_showcase
showcase: vessel
	mkdir -p $(SHOWCASE_TMP)
	cargo run --release -- cut --union -i $(OUT_DIR)/first_wall.step    -o $(SHOWCASE_TMP)/first_wall.step    -s -1/36 -e 1/36
	cargo run --release -- cut --union -i $(OUT_DIR)/breeder.step       -o $(SHOWCASE_TMP)/breeder.step       -s -1/18 -e 1/18
	cargo run --release -- cut --union -i $(OUT_DIR)/back_wall.step     -o $(SHOWCASE_TMP)/back_wall.step     -s -1/12 -e 1/12
	cargo run --release -- cut --union -i $(OUT_DIR)/shield.step        -o $(SHOWCASE_TMP)/shield.step        -s -1/9  -e 1/9
	cargo run --release -- cut --union -i $(OUT_DIR)/vacuum_vessel.step -o $(SHOWCASE_TMP)/vacuum_vessel.step -s -5/36 -e 5/36
	cargo run --release -- compound \
		-i $(OUT_DIR)/chamber.step \
		-i $(SHOWCASE_TMP)/first_wall.step \
		-i $(SHOWCASE_TMP)/breeder.step \
		-i $(SHOWCASE_TMP)/back_wall.step \
		-i $(SHOWCASE_TMP)/shield.step \
		-i $(SHOWCASE_TMP)/vacuum_vessel.step \
		--input-magnet $(COILS_IN) \
		-o $(OUT_DIR)/showcase.step
