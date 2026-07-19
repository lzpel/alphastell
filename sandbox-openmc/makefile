# sandbox-openmc: Docker 内 OpenMC で 14.1 MeV 点線源 + リチウム球の中性子輸送を計算し、
# 未衝突中性子束の減衰を解析解 phi(r)=S*exp(-Sigma_t*r)/(4*pi*r^2) と比較する。CAD 不要。
#
#   make (paper)              # 環境確認は別途 env。data → 解算 → 解析解比較 → レポート PDF
#   make env                  # OpenMC 実行環境の確認 (openmc 版・DAGMC 有無・断面積) ★issue #4 の1本目
#   make data                 # 検証用の軽量断面積ライブラリを生成 (Li6/Li7、初回のみ DL)
#   make compare              # レポートを作らず解析解比較まで
#   make R=40 PARTICLES=500000 paper   # 半径・ヒストリ数を変えて再実行
#   make LIB=full data        # ENDF/B-VIII.0 フルライブラリ (数 GB) に切り替え
#   make clean                # 生成物を削除 (data/ の断面積は残す)

R         ?= 20          # 球半径 [cm]
PARTICLES ?= 200000      # ヒストリ数/バッチ
BATCHES   ?= 20
SHELLS    ?= 20          # 未衝突束の空間分布を測る球シェル数
ENRICH    ?=             # Li6 原子分率 (空=天然組成)
LIB       ?= lite        # lite (Li6/Li7 数MB) | full (ENDF/B-VIII.0 数GB)
IMAGE     ?= openmc/openmc:latest
UV        ?= uv

XS   = data/lib/cross_sections.xml
ENRICH_ARG = $(if $(ENRICH),--enrichment $(ENRICH),)

# OpenMC の docker 起動をここに集約する。断面積は実行時にマウントして参照する
# (issue #4 の方針「断面積は実行時マウント」)。
# MSYS_NO_PATHCONV=1: Git Bash (Windows) が -w /work を Windows パスへ変換するのを防ぐ
#   (Linux/macOS では未使用の無害な環境変数)。report.tex と同じ対処。
# USERSPEC: Linux ホストでは --user で root 所有ファイルを残さない。Windows の
#   Docker Desktop はバインドマウントに Unix 所有権を課さず、MSYS の uid は
#   コンテナに存在しないので、Windows では make USERSPEC= で空にする (README 参照)。
USERSPEC ?= --user $$(id -u):$$(id -g)
OPENMC = MSYS_NO_PATHCONV=1 docker run --rm -v $(CURDIR):/work -w /work \
           $(USERSPEC) -e HOME=/tmp \
           -e OPENMC_CROSS_SECTIONS=/work/$(XS) $(IMAGE)

.PHONY: env data run compare paper clean FORCE

# ---- OpenMC 実行環境の確認 (issue #4 の1本目に決着をつける) ----
# openmc の版、DAGMC のリンク有無、断面積の解決状況を印字する。
# 結果は README の「設計判断と根拠」表に実測として転記する。
env:
	@echo "== OpenMC 実行環境の確認 (issue #4-1) =="
	$(OPENMC) bash -c '\
	  echo "-- python openmc --"; python -c "import openmc; print(openmc.__version__)"; \
	  echo "-- openmc executable --"; openmc --version 2>&1 | head -3; \
	  echo "-- DAGMC linkage (ldd) --"; ldd $$(command -v openmc) 2>/dev/null | grep -iE "dagmc|embree|double-down" || echo "  (DAGMC 関連の共有ライブラリは見つからない)"; \
	  echo "-- cross sections --"; echo "  OPENMC_CROSS_SECTIONS=$$OPENMC_CROSS_SECTIONS"; \
	  test -f $$OPENMC_CROSS_SECTIONS && echo "  found" || echo "  未生成 (make data で作成)"; '

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
run: results/tally.json

# ---- 解析解比較 (閾値超過で非ゼロ終了 = 検証の失敗) ----
compare: results/tally.json
	$(UV) run --with numpy --with matplotlib scripts/compare_attenuation.py \
	  --tally results/tally.json --xs results/xs.json \
	  --plot results/attenuation.png --report results/report.txt \
	  --tex results/values.tex

# ---- 計算 → 図・数値を report/ へ取り込み → PDF (report/report.pdf) ----
# report.tex は自己ビルド式 (/tex 規約): sh report.tex が texlive/texlive の
# latexmk -lualatex を起動する。初回は docker pull texlive/texlive (約5GB)。
paper: compare
	$(UV) run --with numpy --with matplotlib scripts/visualize_condition.py \
	  --out results/condition.png --radius $(R)
	cp results/attenuation.png report/fig01.png
	cp results/condition.png report/fig02.png
	cp results/values.tex report/values.tex
	sh report.tex

clean:
	rm -rf results \
	  report/fig01.png report/fig02.png report/values.tex \
	  report/*.pdf report/*.aux report/*.log \
	  report/*.bbl report/*.blg report/*.out report/*.fls report/*.fdb_latexmk
	@echo "note: data/ の断面積ライブラリは残す (再DL回避)。消すなら rm -rf data"
