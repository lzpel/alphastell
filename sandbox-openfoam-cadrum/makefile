# sandbox-openfoam-cadrum: cadrum の色付き B-rep から2ケースを生成・解算し、
# 統合レポート PDF を出す
#   1. hartmann: 箱 (解析解による検証, 既定 HA=20)
#   2. cone:     環状先細ダクト (cone−cylinder の boolean, MHD デモ, 既定 HA_CONE=5)
#
#   make (paper)      # 両ケース生成 → 解算 → 検証 → レポート PDF (report/report.pdf)
#   make compare      # hartmann の解析解比較まで
#   make verify-cone  # cone の質量保存・プロファイル検証まで
#   make clean        # 生成物を全削除

HA      ?= 20
HA_CONE ?= 5
UV      ?= uv

# ソルバーは epotFoam 焼き込み済みイメージ ghcr.io/lzpel/openfoam を使う
# (ビルド元: ../docker_openfoam)。--user は不要: イメージの entrypoint が
# カレントディレクトリ (-w) の所有者 uid:gid に setpriv で降格する。

.PHONY: solve-hartmann solve-cone compare verify-cone paper clean FORCE

# 両ケースの計算 → 図・数値を report/ へ取り込み → PDF
paper: compare verify-cone
	cp results/hartmann_Ha$(HA).png report/fig01.png
	cp results/geometry.png report/fig02.png
	cp results/geometry_cone.png report/fig03.png
	cp results/cone_profiles.png report/fig04.png
	cp results/values_Ha$(HA).tex report/values.tex
	cp results/values_cone.tex report/values_cone.tex
	sh report.tex

# ---- ケース生成 (色付き B-rep → polyMesh + 0/) ----
hartmann/constant/polyMesh/points: examples/hartmann.rs src/lib.rs Cargo.toml
	cargo run --release --example hartmann

cone/constant/polyMesh/points: examples/cone.rs src/lib.rs Cargo.toml
	cargo run --release --example cone

# ---- HA が変わったときだけ書き換える (タイムスタンプ無駄更新を避ける) ----
hartmann/constant/electromagneticProperties: FORCE
	@sed 's/@HA@/$(HA)/' hartmann/constant/electromagneticProperties.template > $@.tmp; \
	if cmp -s $@.tmp $@; then rm -f $@.tmp; else mv $@.tmp $@; echo "HA=$(HA) -> $@"; fi

cone/constant/electromagneticProperties: FORCE
	@sed 's/@HA@/$(HA_CONE)/' cone/constant/electromagneticProperties.template > $@.tmp; \
	if cmp -s $@.tmp $@; then rm -f $@.tmp; else mv $@.tmp $@; echo "HA_CONE=$(HA_CONE) -> $@"; fi

# ---- 解算 ----
solve-hartmann: hartmann/constant/polyMesh/points hartmann/constant/electromagneticProperties
	rm -rf hartmann/postProcessing hartmann/[1-9]* hartmann/0.[0-9]*
	docker run --rm -v $(CURDIR):/work -w /work \
	  ghcr.io/lzpel/openfoam epotFoam -case hartmann > hartmann/log.epotFoam

solve-cone: cone/constant/polyMesh/points cone/constant/electromagneticProperties
	rm -rf cone/postProcessing cone/[1-9]* cone/0.[0-9]*
	docker run --rm -v $(CURDIR):/work -w /work \
	  ghcr.io/lzpel/openfoam epotFoam -case cone > cone/log.epotFoam

# ---- 検証 (スクリプトは hartmann のみ sandbox-openfoam と共有) ----
compare: solve-hartmann
	$(UV) run --with numpy --with matplotlib ../sandbox-openfoam/scripts/compare_hartmann.py \
	  --ha $(HA) \
	  --profile "$$(ls -d hartmann/postProcessing/sample/*/ | sort -V | tail -1)centreProfile_U.xy" \
	  --plot results/hartmann_Ha$(HA).png --report results/report_Ha$(HA).txt \
	  --tex results/values_Ha$(HA).tex

verify-cone: solve-cone
	$(UV) run --with numpy --with matplotlib scripts/verify_cone.py \
	  --case cone --ha $(HA_CONE) \
	  --plot results/cone_profiles.png --report results/report_cone.txt \
	  --tex results/values_cone.tex

clean:
	cargo clean
	rm -rf results \
	  hartmann/log.* hartmann/postProcessing \
	  hartmann/0 hartmann/constant/polyMesh hartmann/constant/electromagneticProperties \
	  hartmann/[1-9]* hartmann/0.[0-9]* \
	  cone/log.* cone/postProcessing \
	  cone/0 cone/constant/polyMesh cone/constant/electromagneticProperties \
	  cone/[1-9]* cone/0.[0-9]* \
	  report/fig01.png report/fig02.png report/fig03.png report/fig04.png \
	  report/values.tex report/values_cone.tex \
	  report/*.pdf report/*.aux report/*.log \
	  report/*.bbl report/*.blg report/*.out report/*.fls report/*.fdb_latexmk
