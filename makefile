.PHONY:paper download
# OpenMC は cross_sections.xml のパスを見る (ディレクトリではない)
export OPENMC_CROSS_SECTIONS=out/cross_sections/cross_sections.xml
al-%: $(OPENMC_CROSS_SECTIONS)
	$(eval SCRIPT := $(shell find examples -name "al_$*_*.py" -print -quit))
	$(if $(findstring docker,$(shell head -n 1 $(SCRIPT))),sh -c ./$(SCRIPT),uv run $(SCRIPT))
	[ -n "$$SKIP_PDF" ] || uv run examples/md2pdf.py $(SCRIPT:examples/%.py=out/%.md)
	cd out && find . -maxdepth 1 -regextype posix-extended -iregex '.+(md|png|svg|step)' -exec install -D {} pages/{} \;
paper:
	bash ./paper.tex
$(OPENMC_CROSS_SECTIONS): # curlでFENDL3.2を落としてくる核融合用の評価済みライブラリで ENDF/B より小さい
	mkdir out && curl -L -o out/fendl-3.2.tar.xz https://anl.box.com/shared/static/3cb7jetw7tmxaw6nvn77x6c578jnm2ey.xz
	tar -xJf out/fendl-3.2.tar.xz --transform="s,^[^/]+,out/cross_sections,x" --show-transformed-names
