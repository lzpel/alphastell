"""生成した .h5m を OpenMC の DAGMCUniverse として読めるか確認する。

DAGMCUniverse.n_cells / n_surfaces は h5py で .h5m を直接読む実装なので、
共有ライブラリ (openmc.lib) を必要としない。sandbox-openmc-source は libopenmc を
静的に建てて openmc.lib を読めない構成なので、この性質が効いている。

実行: <sandbox-openmc-source の venv python> scripts/read_h5m.py --h5m results/box.h5m --cells 2
"""

import argparse
import sys

import openmc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--h5m", required=True)
    p.add_argument("--cells", type=int, default=None,
                   help="期待するセル数 (ソリッド数 + 陰的補集合1)")
    args = p.parse_args()

    u = openmc.DAGMCUniverse(args.h5m)
    print(f"  n_cells   : {u.n_cells}")
    print(f"  n_surfaces: {u.n_surfaces}")
    try:
        print(f"  materials : {u.material_names}")
    except Exception as e:  # 材料名の取得は版によって挙動が違うので致命にしない
        print(f"  materials : (取得不可: {e})")

    if args.cells is not None and u.n_cells != args.cells:
        print(f"FAIL: n_cells が不一致 (期待 {args.cells}, 実際 {u.n_cells})")
        sys.exit(1)
    print("PASS: OpenMC が DAGMC ジオメトリとして読めた")


if __name__ == "__main__":
    main()
