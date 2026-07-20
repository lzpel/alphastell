"""CadQuery で最小形状を作り、cad_to_dagmc で DAGMC の .h5m に変換する。

このスクリプトの目的は形状を作ることではなく、**conda も WSL も使わない素の Windows +
uv だけで STEP → .h5m が成立するか**を確かめること。.h5m は MOAB のファイル形式なので、
従来この変換には pymoab が要り、pymoab は conda-forge の moab パッケージにしか無く、
それは skip: win で Windows ビルドが存在しなかった。

cad_to_dagmc は 2026-01 に pymoab 依存を外して h5py で MOAB のスキーマを直接書く経路を
既定にしたので、その前提が変わっている。ここではそれを実行で確かめる。

実行: uv run --with cad-to-dagmc scripts/make_h5m.py --out results
"""

import argparse
import os

import cadquery as cq
from cad_to_dagmc import CadToDagmc


def build_shape(kind, size):
    """材料タグを付ける対象の最小形状。

    box  : 立方体1個。面が6枚と数えやすく、期待値を暗算できる
    shells: 同心の立方体殻2個。材料が2つになるので、材料タグの割り当てが
            volume ごとに効いているかを見られる (TBR 本番は多材料なので、
            そこに近い形を1つ通しておく)
    """
    if kind == "box":
        solids = [cq.Workplane("XY").box(size, size, size)]
        tags = ["mat1"]
    elif kind == "shells":
        inner = cq.Workplane("XY").box(size, size, size)
        outer = (
            cq.Workplane("XY").box(size * 2, size * 2, size * 2)
            .cut(cq.Workplane("XY").box(size, size, size))
        )
        solids = [inner, outer]
        tags = ["mat1", "mat2"]
    else:
        raise SystemExit(f"unknown shape: {kind}")
    return solids, tags


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--shape", choices=["box", "shells"], default="box")
    p.add_argument("--size", type=float, default=10.0, help="代表寸法 [cm]")
    p.add_argument("--out", default="results")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    solids, tags = build_shape(args.shape, args.size)

    step_path = os.path.join(args.out, f"{args.shape}.step")
    h5m_path = os.path.join(args.out, f"{args.shape}.h5m")

    # STEP を経由するのは、本番 (cadrum が吐く色付き STEP) と同じ入口を踏むため。
    # CadQuery のオブジェクトを直接渡す API もあるが、それでは STEP リーダを検証できない。
    assy = cq.Assembly()
    for i, s in enumerate(solids):
        assy.add(s, name=f"solid{i}")
    assy.save(step_path, exportType="STEP")
    print(f"  STEP: {step_path}")

    model = CadToDagmc()
    model.add_stp_file(step_path, material_tags=tags)
    # h5m_backend は既定で "h5py"。pymoab を使わないのがこの検証の要点なので、
    # 既定に頼らず明示しておく (上流が既定を戻したら即座に気づけるように)。
    model.export_dagmc_h5m_file(filename=h5m_path, h5m_backend="h5py")
    print(f"  h5m : {h5m_path}")
    print(f"  材料タグ: {tags}")


if __name__ == "__main__":
    main()
