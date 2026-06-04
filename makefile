export MSYS_NO_PATHCONV := 1
MAKE_RECURSIVE_DIRS := frontend/openapi frontend
export MAKE_RECURSIVE = time printf '%s\n' $(MAKE_RECURSIVE_DIRS) | xargs -IX sh -c '$(MAKE) -C X $@ || exit 255'

VMEC_IN  := resource/wout_vmec.nc
COILS_IN := resource/coils.example
PARA_DIR := parastell/examples/alphastell_full
OUT_DIR  := out

# Rust の vessel が一括出力する 6 層 (内側 → 外側)。
# chamber は parastell の plasma.step と概念的に対応 (ファイル名のみ別)。
LAYERS := chamber first_wall breeder back_wall shield vacuum_vessel

.DEFAULT_GOAL := help

help: ## このヘルプを表示
	@grep -hE '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ============================================================
# submodule — parastell/ git submodule を init/update。
#   validate / bbox の参照 .step ($(PARA_DIR)/*.step) はここで揃う。
#   通常パイプライン (vessel/magnet) は resource/ を使うので不要。
# ============================================================
submodule: ## parastell submodule を init/update
	git submodule update --init --recursive

run: vessel magnet ## vessel + magnet を一括生成

# ============================================================
# generate frontend
# ============================================================

frontend-generate: ## wout_vmec.nc を strip して frontend を生成
	cargo run -- strip-netcdf \
      --input $(VMEC_IN) \
      --output frontend/public/wout_vmec.nc \
      --include xm --include xn --include rmnc --include zmns
	find . -maxdepth 2 -name .gitignore | xargs -IX sed '/^#\s*EOF_DOCKERIGNORE.*/q' X > .dockerignore
	bash -c "$${MAKE_RECURSIVE}"
frontend-run-backend: ## backend サーバを起動
	cargo run -- server --port 7998 --port-frontend 7999
frontend-run-frontend: ## frontend dev サーバを起動
	PORT=7999 make -C frontend frontend-run
frontend-run: frontend-run-backend frontend-run-frontend ## backend + frontend を起動
	# bash -c "$${MAKE_RECURSIVE}"
frontend-deploy: frontend-generate ## frontend をビルド (embed release)
	bash -c "$${MAKE_RECURSIVE}"
	cargo build --features frontend-embed --release
frontend-publish: frontend-deploy ## frontend を AWS へデプロイ
	make -C aws deploy

# ============================================================
# vessel — 6 層 in-vessel build を一括生成
#   出力: $(OUT_DIR)/{chamber,first_wall,breeder,back_wall,shield,vacuum_vessel}.step
#   wall_s=1.08 を基準に mesh() + boolean_subtract で構築 (Solid::shell は使わない)。
# ============================================================
vessel: $(VMEC_IN) ## 6 層 in-vessel build を生成
	cargo run --release -- vessel --scale 100 --input $(VMEC_IN) --output $(OUT_DIR)/

# ============================================================
# magnet — coils.example から長方形断面 sweep で magnet_set.step を生成 (m 単位)
# ============================================================
magnet: $(COILS_IN) ## coils から magnet_set.step を生成
	cargo run --release -- magnet --scale 100 --input $(COILS_IN) --output $(OUT_DIR)/

# ============================================================
# validate — 各層を parastell 参照と体積比較
#   Rust chamber.step ↔ parastell plasma.step (最内領域は命名違いだが同じ体積)。
#   他 5 層はファイル名が一致。
#   tol=0.05 は s=1.08 外挿 + Planar 2D 法線近似に由来する数 % 程度のズレを許容。
# ============================================================
validate: $(addprefix validate-,$(LAYERS)) ## 全層を parastell 参照と体積比較

# 各 validate-LAYER は parastell/examples/alphastell_full/*.step (submodule 配下) を
# 参照対象として読むので、submodule ターゲットに依存させて init を効かせる。
$(addprefix validate-,$(LAYERS)): submodule

validate-chamber: ## chamber を plasma.step と体積比較
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/chamber.step $(PARA_DIR)/plasma.step

validate-first_wall: ## first_wall を体積比較
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/first_wall.step $(PARA_DIR)/first_wall.step

validate-breeder: ## breeder を体積比較
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/breeder.step $(PARA_DIR)/breeder.step

validate-back_wall: ## back_wall を体積比較
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/back_wall.step $(PARA_DIR)/back_wall.step

validate-shield: ## shield を体積比較
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/shield.step $(PARA_DIR)/shield.step

validate-vacuum_vessel: ## vacuum_vessel を体積比較
	cargo run --release -- validate --tol 0.05 $(OUT_DIR)/vacuum_vessel.step $(PARA_DIR)/vacuum_vessel.step

# ============================================================
# bbox — parastell/examples/alphastell_full 下の全 *.step の bbox を列挙
#   1 行 1 ファイル: path x0 y0 z0 x1 y1 z1 dx dy dz
# ============================================================
bbox: submodule ## out/ と parastell 参照の bbox を列挙
	cargo run --release -- bbox $(wildcard $(OUT_DIR)/*.step)
	cargo run --release -- bbox $(wildcard $(PARA_DIR)/*.step)

# ============================================================
# points — $(OUT_DIR) 下の *.csv をすべて matplotlib 3D 散布で重ね表示
#   header 有無は自動判定、末尾 3 列を (x, y, z) として扱う。
#   vessel (*.csv) / magnet (magnet_set.csv) ともに m 単位で同スケール、
#   重ねて viewing してもそのまま整合する。
#   環境変数 VIEW="azim,elev,roll" / OUTPUT=path で起動時の視点 / 保存先を指定可能。
# ============================================================
points: points-save ## out/*.csv を 3D 散布表示
	uv run tools/view_points.py ./$(OUT_DIR)

points-save: ## out/*.csv を points.png に保存
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
showcase: run ## cutaway STEP/SVG を生成
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
