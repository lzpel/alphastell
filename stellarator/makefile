# stellarator: VMEC 平衡 (wout.nc) の読み込み・フーリエ評価・スプライン放射補間の
# 単体検証。cadrum (CAD カーネル) は使わない純粋な数学計算のみ。alphastell の
# core/src/vmec.rs を移植し、磁気面の点群を出して形状の妥当性を定量判定する。
#
#   make (test)   # 無ければ release から wout を取得 → cargo test → 点群 CSV → 図と判定
#   make clean    # 生成物を削除 (out/ の wout は残す)
#   make PATH_WMEC=/path/to/wout.nc test   # 別の wout で回す
#

.PHONY: test clean

# 一発で通す: フィクスチャ取得 → テスト (CSV 生成) → 図と定量判定。
test:
	mkdir -p out
	PATH_WMEC=./wout_vmec.nc cargo test --release -- --nocapture
	uv run scripts/plot_surface.py --csv out/surface_points.csv --wout ./wout_vmec.nc --plot out/surface.png --report out/report.txt --tex out/values.tex

clean:
	cargo clean
