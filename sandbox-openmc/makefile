# sandbox-openmc: OpenMC (openmc-pypi wheel、uv 管理) で 14.1 MeV 点線源 + リチウム球の
# 中性子輸送を計算し、未衝突中性子束の減衰を解析解 phi(r)=S*exp(-Sigma_t*r)/(4*pi*r^2) と
# 比較する。CAD 不要。Docker も不要 (issue #16。report.tex の texlive だけは別)。
#
#   make (paper)              # 解算 → 解析解比較 → レポート PDF (report/report.pdf)
#   make data                 # 検証用の軽量断面積ライブラリを生成 (Li6/Li7、初回のみ DL)
#   make R=40 PARTICLES=500000 paper   # 半径・ヒストリ数を変えて再実行
#   make LIB=full data        # ENDF/B-VIII.0 フルライブラリ (数 GB) に切り替え
#   make clean                # 生成物を削除 (data/ の断面積は残す)

R         ?= 20          # 球半径 [cm]
PARTICLES ?= 200000      # ヒストリ数/バッチ
BATCHES   ?= 20
SHELLS    ?= 20          # 未衝突束の空間分布を測る球シェル数
ENRICH    ?=             # Li6 原子分率 (空=天然組成)
LIB       ?= lite        # lite (Li6/Li7 数MB、同梱 njoy で変換) | full (ENDF/B-VIII.0 数GB)
UV        ?= uv

XS   = data/lib/cross_sections.xml
ENRICH_ARG = $(if $(ENRICH),--enrichment $(ENRICH),)

# OpenMC の起動をここに集約する。uv run が pyproject.toml の依存 (openmc-pypi wheel:
# openmc 実行ファイル・libopenmc・njoy を同梱) を .venv に用意し、その Scripts/bin を
# PATH に前置するので、model.py の Model.run() (literal 'openmc') と build_xs.py の
# from_njoy (literal 'njoy') がそのまま解決する。断面積は環境変数で渡す。
# sandbox-openmc-source 連携の `make paper OPENMC=<openmc-env のパス>` 上書き規約は
# 従来どおり (上書き時は環境変数ごと置き換わる。openmc-env は自前で export する)。
OPENMC = OPENMC_CROSS_SECTIONS=$(CURDIR)/$(XS) $(UV) run

.PHONY: paper data clean FORCE
# レシピが非ゼロ終了したら書きかけのターゲットを消す。compare の閾値超過 (検証失敗) で
# 中途半端な values.tex が残ると、次の make が黙って成功してしまうため。
.DELETE_ON_ERROR:

# ---- 計算 → 図・数値を report/ へ取り込み → PDF (report/report.pdf) ----
# report.tex は自己ビルド式 (/tex 規約): sh report.tex が texlive/texlive の
# latexmk -lualatex を起動する。初回は docker pull texlive/texlive (約5GB)。
paper: results/values.tex
	$(OPENMC) python scripts/visualize_condition.py \
	  --out results/condition.png --radius $(R)
	cp results/attenuation.png report/fig01.png
	cp results/condition.png report/fig02.png
	cp results/values.tex report/values.tex
	sh report.tex

# ---- 断面積ライブラリ (実ファイルターゲット、clean では消さない) ----
$(XS): scripts/build_xs.py
	$(OPENMC) python scripts/build_xs.py --mode $(LIB) --out data
data: $(XS)

# ---- パラメータ変更で再実行させるためのスタンプ (値が変わったときだけ更新) ----
results/params.stamp: FORCE
	@mkdir -p results; \
	echo 'R=$(R) N=$(PARTICLES) B=$(BATCHES) S=$(SHELLS) E=$(ENRICH)' > $@.tmp; \
	if cmp -s $@.tmp $@; then rm -f $@.tmp; else mv $@.tmp $@; echo "params -> $$(cat $@)"; fi

# ---- 解算 (tally.json + xs.json を results/ に出力) ----
results/tally.json: model.py results/params.stamp $(XS)
	$(OPENMC) python model.py --radius $(R) --particles $(PARTICLES) \
	  --batches $(BATCHES) --shells $(SHELLS) $(ENRICH_ARG) --out results

# ---- 解析解比較 (閾値超過で非ゼロ終了 = 検証の失敗) ----
# 4出力のうち values.tex を代表ターゲットにする (paper が依存する最終成果物)。
results/values.tex: scripts/compare_attenuation.py results/tally.json
	$(OPENMC) python scripts/compare_attenuation.py \
	  --tally results/tally.json --xs results/xs.json \
	  --plot results/attenuation.png --report results/report.txt \
	  --tex results/values.tex

clean:
	rm -rf results \
	  report/fig01.png report/fig02.png report/values.tex \
	  report/*.pdf report/*.aux report/*.log \
	  report/*.bbl report/*.blg report/*.out report/*.fls report/*.fdb_latexmk
	@echo "note: data/ の断面積ライブラリは残す (再DL回避)。消すなら rm -rf data"
