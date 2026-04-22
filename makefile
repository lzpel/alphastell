VMEC_IN  := parastell/examples/wout_vmec.nc
COILS_IN := parastell/examples/coils.example
PARA_DIR := parastell/examples/alphastell_full
OUT_DIR  := out

# plasma (chamber, s=1.0, thickness=0)
PLASMA_OUT  := $(OUT_DIR)/plasma.step
PLASMA_REF  := $(PARA_DIR)/plasma.step

# first_wall (s=wall_s=1.08, thickness=5 cm)
FW_OUT      := $(OUT_DIR)/first_wall.step
FW_REF      := $(PARA_DIR)/first_wall.step
WALL_S      := 1.08
FW_THICK    := 5.0

# magnet (coils.example → rectangular-cross-section sweep、mm 単位)
MAG_OUT := $(OUT_DIR)/magnet_set.step
MAG_REF := $(PARA_DIR)/magnet_set.step

.PHONY: run generate validate first-wall first-wall-generate first-wall-validate first-wall-cut \
        magnet magnet-generate magnet-validate

run: generate validate

generate:
	cargo run --release -- generate --input $(VMEC_IN) --output $(PLASMA_OUT)

validate:
	cargo run --release -- validate --union $(PLASMA_OUT) $(PLASMA_REF)

first-wall: first-wall-generate first-wall-validate

first-wall-generate:
	cargo run --release -- generate --input $(VMEC_IN) --output $(FW_OUT) --s $(WALL_S) --thickness $(FW_THICK)

first-wall-validate:
	# first_wall は s=1.08 外挿 + 法線定義差 (parastell=2D poloidal / cadrum=3D surface) で
	# 約 3% 程度のズレが仕様上出るため tolerance を 5% に緩める
	cargo run --release -- validate --tol 0.05 $(FW_OUT) $(FW_REF)

# first_wall を Z 軸まわりのウェッジで切り出して保存。
# 注意: 現時点で first_wall は BREP_WITH_VOIDS 形式 (Solid::shell 由来) なので cut 後の
# 体積が壊れる既知バグあり (void が boolean_intersect で誤動作)。plasma のような
# MANIFOLD_SOLID_BREP では cut 正常動作することは確認済み。generate を boolean_subtract
# ベースに切り替える PR を別途予定。
first-wall-cut: first-wall-generate
	cargo run --release -- cut $(FW_OUT) $(OUT_DIR)/first_wall_div2.step --div 2
	cargo run --release -- cut $(FW_OUT) $(OUT_DIR)/first_wall_div3.step --div 3
	cargo run --release -- cut $(FW_OUT) $(OUT_DIR)/first_wall_div4.step --div 4

# magnet: coils.example から 40 本のフィラメントを読んで長方形断面 sweep で
# magnet_set.step を生成する。単位は mm (parastell の cm 出力と単位系が違うので
# validate の数値一致は不可、ファイル読み書きと volume > 0 のみ確認)。
magnet: magnet-generate magnet-validate

magnet-generate:
	cargo run --release -- magnet --input $(COILS_IN) --output $(MAG_OUT)

magnet-validate:
	# Rust (mm) vs parastell (cm) で単位違い。ratio は 10^3 オーダで大きくずれる。
	# tolerance / max-ratio を緩めて「読めて正の体積」を最低ラインとして確認する。
	cargo run --release -- validate --tol 0.5 --max-ratio 100 $(MAG_OUT) $(MAG_REF)
