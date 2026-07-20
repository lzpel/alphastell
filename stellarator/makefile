# stellarator: VMEC 平衡 (wout.nc) の読み込み・フーリエ評価・スプライン放射補間の
# 単体検証。cadrum (CAD カーネル) は使わない純粋な数学計算のみ。alphastell の
# core/src/vmec.rs を移植し、磁気面の点群を出して形状の妥当性を定量判定する。
#
#   make (test)   # 無ければ release から wout を取得 → cargo test → 点群 CSV → 図と判定
#   make clean    # 生成物を削除 (out/ の wout は残す)
#   make PATH_WMEC=/path/to/wout.nc test   # 別の wout で回す
#
# リポジトリルートからは `make -C stellarator` で呼べる。

PATH_WMEC ?= out/wout_vmec.nc
WOUT_URL  ?= https://github.com/lzpel/mhd-tbr-stell/releases/download/resource-v1/wout_vmec.nc

.PHONY: test clean

# 一発で通す: フィクスチャ取得 → テスト (CSV 生成) → 図と定量判定。
test:
	@mkdir -p out results
	@if [ ! -f "$(PATH_WMEC)" ]; then \
	  echo "fetching wout_vmec.nc ..."; \
	  curl -fL --retry 3 -o "$(PATH_WMEC)" "$(WOUT_URL)"; \
	fi
	@if ! head -c 4 "$(PATH_WMEC)" | grep -q CDF; then echo "FAIL: $(PATH_WMEC) is not netCDF"; exit 1; fi
	PATH_WMEC=$(PATH_WMEC) cargo test --release -- --nocapture
	uv run --with numpy --with matplotlib --with scipy scripts/plot_surface.py \
	  --csv results/surface_points.csv --wout $(PATH_WMEC) \
	  --plot results/surface.png --report results/report.txt --tex results/values.tex

clean:
	cargo clean
	rm -rf results
	@echo "note: out/ は残す (8.3 MB の再取得回避)。消すなら rm -rf out"
