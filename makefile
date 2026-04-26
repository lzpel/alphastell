export MSYS_NO_PATHCONV := 1
MAKE_RECURSIVE_DIRS := openapi frontend
export MAKE_RECURSIVE = time printf '%s\n' $(MAKE_RECURSIVE_DIRS) | xargs -IX sh -c '$(MAKE) -C X $@ || exit 255'

VMEC_IN  := parastell/examples/wout_vmec.nc
COILS_IN := parastell/examples/coils.example
PARA_DIR := parastell/examples/alphastell_full
OUT_DIR  := out

# Rust の vessel が一括出力する 6 層 (内側 → 外側)。
# chamber は parastell の plasma.step と概念的に対応 (ファイル名のみ別)。
LAYERS := chamber first_wall breeder back_wall shield vacuum_vessel

# ============================================================
# Submodule auto-init: parastell/ は git submodule。
# `git clone --recurse-submodules` 忘れでも、$(VMEC_IN) が無ければ初回だけ
# `git submodule update --init --recursive` を一回実行する。同 init で
# $(COILS_IN) / $(PARA_DIR)/*.step も同時に揃うので、それらは $(VMEC_IN) を
# 依存にぶら下げて連鎖取得させれば十分。init 済みなら recipe はスキップ。
# ============================================================
$(VMEC_IN):
	git submodule update --init --recursive

$(COILS_IN): $(VMEC_IN)

run: vessel magnet

# ============================================================
# デモサーバーを起動
# ============================================================

server-generate:
	bash -c "$${MAKE_RECURSIVE}"
server-run:
	cargo install --root out rebab
	out/bin/rebab --frontend 127.0.0.1:8000 --rule "prefix=/api,port=7998,command=cargo run -- server" --rule "port=7999,command=make -C frontend server-run"
	# bash -c "$${MAKE_RECURSIVE}"
server-deploy:
	bash -c "$${MAKE_RECURSIVE}"

# ============================================================
# vessel — 6 層 in-vessel build を一括生成
#   出力: $(OUT_DIR)/{chamber,first_wall,breeder,back_wall,shield,vacuum_vessel}.step
#   wall_s=1.08 を基準に mesh() + boolean_subtract で構築 (Solid::shell は使わない)。
# ============================================================
vessel: $(VMEC_IN)
	cargo run --release -- vessel --wall-s 1.08 --scale 100 --input $(VMEC_IN) --output $(OUT_DIR)/

# ============================================================
# magnet — coils.example から長方形断面 sweep で magnet_set.step を生成 (m 単位)
# ============================================================
magnet: $(COILS_IN)
	cargo run --release -- magnet --scale 100 --input $(COILS_IN) --output $(OUT_DIR)/magnet_set.step

# ============================================================
# validate — 各層を parastell 参照と体積比較
#   Rust chamber.step ↔ parastell plasma.step (最内領域は命名違いだが同じ体積)。
#   他 5 層はファイル名が一致。
#   tol=0.05 は s=1.08 外挿 + Planar 2D 法線近似に由来する数 % 程度のズレを許容。
# ============================================================
validate: $(addprefix validate-,$(LAYERS))

# 各 validate-LAYER は parastell/examples/alphastell_full/*.step (submodule 配下) を
# 参照対象として読むので、$(VMEC_IN) sentinel に依存させて自動 init を効かせる。
$(addprefix validate-,$(LAYERS)): $(VMEC_IN)

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
# bbox — parastell/examples/alphastell_full 下の全 *.step の bbox を列挙
#   1 行 1 ファイル: path x0 y0 z0 x1 y1 z1 dx dy dz
# ============================================================
bbox:
	cargo run --release -- bbox $(wildcard $(OUT_DIR)/*.step)
	cargo run --release -- bbox $(wildcard $(PARA_DIR)/*.step)

# ============================================================
# points — $(OUT_DIR) 下の *.csv をすべて matplotlib 3D 散布で重ね表示
#   header 有無は自動判定、末尾 3 列を (x, y, z) として扱う。
#   vessel (*.csv) / magnet (magnet_set.csv) ともに m 単位で同スケール、
#   重ねて viewing してもそのまま整合する。
#   環境変数 VIEW="azim,elev,roll" / OUTPUT=path で起動時の視点 / 保存先を指定可能。
# ============================================================
points: points-save
	uv run tools/view_points.py ./$(OUT_DIR)

points-save:
	OUTPUT=$(OUT_DIR)/points.png uv run tools/view_points.py ./$(OUT_DIR)

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
#     i=6  magnet (±1/6) : $(OUT_DIR)/magnet_set.step を -i で挿入 (cut せずそのまま)
#
#   vessel 6 層 + magnet は compound::run が hsv(i*0.2/N, 1, 1) の穏やかな gradient で着色。
#   同名 out/showcase.svg も自動生成 (-X 方向投影、隠線 + shading)。
# ============================================================
showcase: run
	mkdir -p $(OUT_DIR)/showcase
	cargo run --release -- cut --union -i $(OUT_DIR)/first_wall.step    -o $(OUT_DIR)/showcase/first_wall.step    -s -1/36 -e 1/36
	cargo run --release -- cut --union -i $(OUT_DIR)/breeder.step       -o $(OUT_DIR)/showcase/breeder.step       -s -1/18 -e 1/18
	cargo run --release -- cut --union -i $(OUT_DIR)/back_wall.step     -o $(OUT_DIR)/showcase/back_wall.step     -s -1/12 -e 1/12
	cargo run --release -- cut --union -i $(OUT_DIR)/shield.step        -o $(OUT_DIR)/showcase/shield.step        -s -1/9  -e 1/9
	cargo run --release -- cut --union -i $(OUT_DIR)/vacuum_vessel.step -o $(OUT_DIR)/showcase/vacuum_vessel.step -s -5/36 -e 5/36
	cargo run --release -- compound \
		-i $(OUT_DIR)/chamber.step \
		-i $(OUT_DIR)/showcase/first_wall.step \
		-i $(OUT_DIR)/showcase/breeder.step \
		-i $(OUT_DIR)/showcase/back_wall.step \
		-i $(OUT_DIR)/showcase/shield.step \
		-i $(OUT_DIR)/showcase/vacuum_vessel.step \
		-i $(OUT_DIR)/magnet_set.step \
		-o $(OUT_DIR)/showcase.step
