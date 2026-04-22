VMEC_IN  := parastell/examples/wout_vmec.nc
COILS_IN := parastell/examples/coils.example
PARA_DIR := parastell/examples/alphastell_full
OUT_DIR  := out

# Rust の generate が一括出力する 6 層 (内側 → 外側)。
# chamber は parastell の plasma.step と概念的に対応 (ファイル名のみ別)。
LAYERS := chamber first_wall breeder back_wall shield vacuum_vessel

# magnet (コイル、mm 単位の別サブシステム)
MAG_OUT := $(OUT_DIR)/magnet_set.step
MAG_REF := $(PARA_DIR)/magnet_set.step

.PHONY: run generate \
        validate $(addprefix validate-,$(LAYERS)) \
        cut cut-first-wall \
        magnet magnet-generate magnet-validate \
        view plasma

run: generate validate

# ============================================================
# generate — 6 層 in-vessel build を一括生成
#   出力: $(OUT_DIR)/{chamber,first_wall,breeder,back_wall,shield,vacuum_vessel}.step
#   wall_s=1.08 を基準に mesh() + boolean_subtract で構築 (Solid::shell は使わない)。
# ============================================================
generate:
	cargo run --release -- generate --input $(VMEC_IN) --output $(OUT_DIR)/

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
#   内部は line+arc+line の閉 wire を extrude した扇柱と boolean intersect する方式で、
#   旧 half-space 方式の div>=3 empty 問題は回避済み。
# ============================================================
cut: cut-first-wall

cut-first-wall: generate
	cargo run --release -- cut -i $(OUT_DIR)/first_wall.step -o $(OUT_DIR)/first_wall_half.step -s 0 -e 1/2

# ============================================================
# view — chamber_points.csv を matplotlib で 4 パネル可視化
#   generate 実行時に生 VMEC 単位 (m, scale=1 固定) で出力した CSV を読み、
#   3D 散布 / 上面 (X,Y) / 断面重ね (R,Z) / seam step 比較の PNG を作る。
#   uv が PEP 723 inline スクリプト依存を自動解決するので venv 不要。
# ============================================================
view:
	uv run tools/view_chamber.py --input $(OUT_DIR)/chamber_points.csv --output $(OUT_DIR)/chamber_view.png

# ============================================================
# plasma — VMEC LCFS (s=1.0) を複数 (M, N) 解像度で B-spline STEP 化
#   index_rz 直接 (スプライン補間なし)、scale=1 (m) で生 VMEC 単位。
#   出力: out/plasma_M{m}_N{n}.step を pair リスト分。
#   phi=0/2π seam の Nyquist aliasing 依存性を viewer で並べて切り分ける。
# ============================================================
plasma:
	cargo run --release -- plasma --input $(VMEC_IN) --output $(OUT_DIR)/

# ============================================================
# magnet — coils.example から長方形断面 sweep で magnet_set.step を生成 (mm 単位)
# ============================================================
magnet:
	cargo run --release -- magnet --input $(COILS_IN) --output $(MAG_OUT)
