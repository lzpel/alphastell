# stellarator: VMEC 平衡 (wout.nc) の読み込み・フーリエ評価・スプライン放射補間と、
# その点群から流路ソリッドを作る geometry モジュール (cadrum)。alphastell の
# core/src/vmec.rs を移植し、磁気面の点群を出す。
#
#   make (test)   # cargo test → 点群 CSV
#   make clean    # 生成物を削除 (out/ の wout は残す)
#   make PATH_WMEC=/path/to/wout.nc test   # 別の wout で回す
#

.PHONY: test clean

# 一発で通す: テスト (CSV 生成)。python 側の入口は ../examples/al_*.py。
test:
	mkdir -p out
	PATH_WMEC=../examples/wout_vmec.nc cargo test --release -- --nocapture

clean:
	cargo clean
