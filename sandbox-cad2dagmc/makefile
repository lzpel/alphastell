# sandbox-cad2dagmc: CadQuery で作った STEP を cad_to_dagmc で DAGMC の .h5m に変換し、
# conda も WSL も使わない素の Windows + uv だけで成立するかを検証する。
#
#   make (verify)         # (デフォルト) 生成 → 構造検査 → OpenMC 読み込み確認
#   make h5m              # STEP と .h5m を生成
#   make inspect          # .h5m の構造を h5py で検査 (核データ・OpenMC 不要)
#   make SHAPE=shells     # 2材料の同心殻で実行 (既定は立方体1個)
#   make clean            # 生成物を削除
#
# 検査は DAGMC 必須タグの欠落や Volume 数・材料タグの不一致で **非ゼロ終了**する
# (検証として失敗する)。
#
# 背景: .h5m は MOAB のファイル形式で、従来この変換には pymoab が要った。pymoab は
# conda-forge の moab パッケージにしか無く、それは skip: win で Windows ビルドが無い。
# cad_to_dagmc は 2026-01 に pymoab 依存を外し h5py で MOAB スキーマを直接書く経路を
# 既定にしたので、その前提が変わっている。詳細は README の「設計判断と根拠」。

# SHAPE: box (立方体1個) | shells (同心殻2個、2材料)。SIZE は代表寸法 [cm]。
# 行内コメントは値に含まれてしまうので書かない (make は # の前の空白ごと値に入れる)。
SHAPE ?= box
SIZE  ?= 10
UV    ?= uv

# cad_to_dagmc が引き込む依存はここに集約する。cadquery-ocp (OCCT) と
# cad-to-dagmc-mesher だけがコンパイル済みで、どちらも win_amd64 wheel がある。
C2D = $(UV) run --with cad-to-dagmc

H5M  = results/$(SHAPE).h5m

# 形状ごとの期待値。2つあるのは、数える対象が違うため。
#   SOLIDS  : .h5m の中に実在する Volume の数 (= 入力したソリッド数)。h5py 検査が見る
#   CELLS   : OpenMC が数えるセル数。DAGMC は外側に陰的補集合 (implicit complement) を
#             実行時に1つ足すので SOLIDS + 1 になる。ファイルには入っていない
ifeq ($(SHAPE),shells)
  SOLIDS    = 2
  CELLS     = 3
  MATERIALS = mat1 mat2
else
  SOLIDS    = 1
  CELLS     = 2
  MATERIALS = mat1
endif

# 上流 (Linux + pymoab) が生成した既知良品。手元の OpenMC クローンに同梱されている。
# 生成経路が違うので完全一致はしないが、必須タグの取りこぼしを検出できる。
REFERENCE ?= ../sandbox-openmc-source/src/openmc/tests/regression_tests/dagmc/legacy/dagmc.h5m

# OpenMC 読み込み確認に使う python。sandbox-openmc-source が建てた venv をそのまま使う。
# make -C ../sandbox-openmc-source を呼ばないのは意図的で、あちらは .PHONY のチェーンなので
# 呼ぶと DAGMC 有効ビルドを現在の makefile の設定で建て直してしまう。
OPENMC_PY ?= ../sandbox-openmc-source/venv/Scripts/python.exe

.PHONY: verify h5m inspect clean

# ---- デフォルト: 3段階を通す ----
# (1) 生成できるか (2) 構造が正しいか (3) OpenMC が読めるか。
# どこで落ちたかで意味が変わるので、段を分けたまま順に実行する。
verify: inspect
	@echo "== (3) OpenMC が読めるか =="
	@# 判定と実行を1行に収める。make はレシピ行ごとに別シェルを起こすので、
	@# 前の行で exit 0 してもその行のシェルが終わるだけで次の行は実行されてしまう。
	@if test -x "$(OPENMC_PY)"; then \
	  echo '  "$(OPENMC_PY)" scripts/read_h5m.py --h5m $(H5M) --cells $(CELLS)'; \
	  "$(OPENMC_PY)" scripts/read_h5m.py --h5m $(H5M) --cells $(CELLS); \
	else \
	  echo "  skip: $(OPENMC_PY) not found (build sandbox-openmc-source first)"; \
	fi

# ---- (1) 生成 ----
h5m: $(H5M)

$(H5M): scripts/make_h5m.py
	$(C2D) scripts/make_h5m.py --shape $(SHAPE) --size $(SIZE) --out results

# ---- (2) 構造検査 (核データも OpenMC も要らないので、ここまでを先に通す) ----
inspect: $(H5M)
	@echo "== (2) .h5m の構造検査 =="
	$(UV) run --with h5py --with numpy scripts/inspect_h5m.py --h5m $(H5M) \
	  --volumes $(SOLIDS) --materials $(MATERIALS) \
	  $(if $(wildcard $(REFERENCE)),--reference $(REFERENCE),)

clean:
	rm -rf results __pycache__ scripts/__pycache__
