# sandbox-openfoam: Docker 内 OpenFOAM + epotFoam で Hartmann 流を計算し解析解と比較する
#
#   make (paper)      # ビルド → メッシュ → 解算 → 解析解比較 → レポート PDF (既定 Ha=20)
#   make HA=10 paper  # Hartmann 数を変えて実行 (deltaT ≲ 1/Ha² に注意, controlDict 参照)
#   make compare      # レポートを作らず解析解比較まで
#   make clean        # 生成物を全削除

HA   ?= 20
CASE  = hartmann
UV   ?= uv

# OpenFOAM の docker 起動設定は epotFoam/ に集約されている:
# $$($(MAKE) -s --no-print-directory -C epotFoam) <コマンド> でコンテナ内の OpenFOAM を起動できる
# (foam ターゲットが docker run プレフィックスを出力し、環境設定は epotFoam/openfoam.sh)。

.PHONY: solve compare paper clean FORCE

# 計算 (solve+compare) → 図・数値を report/ へ取り込み → PDF (report/report.pdf)。
# report.tex は自己ビルド式 (/tex 規約): sh report.tex が texlive/texlive の
# latexmk -lualatex を起動する。初回は docker pull texlive/texlive (約5GB)。
paper: compare
	$(UV) run --with numpy --with matplotlib scripts/visualize_condition.py \
	  --out out/boundary_conditions.png
	cp out/hartmann_Ha$(HA).png report/fig01.png
	cp out/boundary_conditions.png report/fig02.png
	cp out/values_Ha$(HA).tex report/values.tex
	sh report.tex

# HA が変わったときだけ書き換える (タイムスタンプ無駄更新を避ける)
$(CASE)/constant/electromagneticProperties: FORCE
	@sed 's/@HA@/$(HA)/' $(CASE)/constant/electromagneticProperties.template > $@.tmp; \
	if cmp -s $@.tmp $@; then rm -f $@.tmp; else mv $@.tmp $@; echo "HA=$(HA) -> $@"; fi

$(CASE)/constant/polyMesh/points: $(CASE)/system/blockMeshDict
	MSYS_NO_PATHCONV=1 $$($(MAKE) -s --no-print-directory -C epotFoam) blockMesh -case $(CASE) > $(CASE)/log.blockMesh

solve: $(CASE)/constant/polyMesh/points $(CASE)/constant/electromagneticProperties
	rm -rf $(CASE)/postProcessing $(CASE)/[1-9]* $(CASE)/0.[0-9]*
	MSYS_NO_PATHCONV=1 $$($(MAKE) -s --no-print-directory -C epotFoam) epotFoam -case $(CASE) > $(CASE)/log.epotFoam

compare: solve
	mkdir -p out
	$(UV) run --with numpy --with matplotlib scripts/compare_hartmann.py \
	  --ha $(HA) \
	  --profile "$$(ls -d $(CASE)/postProcessing/sample/*/ | sort -V | tail -1)centreProfile_U.xy" \
	  --plot out/hartmann_Ha$(HA).png --report out/report_Ha$(HA).txt \
	  --tex out/values_Ha$(HA).tex

clean:
	$(MAKE) -C epotFoam clean
	rm -rf out \
	  $(CASE)/log.* $(CASE)/postProcessing \
	  $(CASE)/constant/polyMesh $(CASE)/constant/electromagneticProperties \
	  $(CASE)/[1-9]* $(CASE)/0.[0-9]* \
	  report/fig01.png report/fig02.png report/values.tex \
	  report/*.pdf report/*.aux report/*.log \
	  report/*.bbl report/*.blg report/*.out report/*.fls report/*.fdb_latexmk
