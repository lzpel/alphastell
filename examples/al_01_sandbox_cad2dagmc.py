#!/usr/bin/env python3
"""CadQuery → STEP → cad_to_dagmc → .h5m → OpenMC 読み込みの一気通貫サンプル。

旧 sandbox-cad2dagmc の凝縮版 (経緯は notes/20260721-cad2dagmcがwindowsで動くか.md)。
検証したいのは形状ではなく、**conda も WSL も使わない素の Windows + uv だけで
STEP → .h5m → OpenMC が成立する**こと。.h5m は MOAB のファイル形式で、従来この変換には
conda-forge にしか無い pymoab が要ったが、cad_to_dagmc が h5py で MOAB スキーマを
直接書く経路を既定にしたので成立するようになった。

代表形状は同心の立方体殻2個 (材料2つ)。材料タグの割り当てが volume ごとに
効いているかを見られる (TBR 本番は多材料なので、そこに近い形を1つ通しておく)。

リポジトリルートで:

    uv run examples/sandbox_cad2dagmc.py
"""

import argparse
import os
import sys

import cadquery as cq
import openmc
from cad_to_dagmc import CadToDagmc


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--size", type=float, default=10.0, help="代表寸法 [cm]")
    p.add_argument("--out", default="out")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)

    # 同心殻2個。内側の立方体と、それをくり抜いた外殻
    inner = cq.Workplane("XY").box(args.size, args.size, args.size)
    outer = (
        cq.Workplane("XY").box(args.size * 2, args.size * 2, args.size * 2)
        .cut(cq.Workplane("XY").box(args.size, args.size, args.size))
    )
    tags = ["mat1", "mat2"]

    # STEP を経由するのは、本番 (cadrum が吐く色付き STEP) と同じ入口を踏むため。
    # CadQuery のオブジェクトを直接渡す API もあるが、それでは STEP リーダを検証できない。
    step_path = os.path.join(args.out, "shells.step")
    h5m_path = os.path.join(args.out, "shells.h5m")
    assy = cq.Assembly()
    for i, s in enumerate((inner, outer)):
        assy.add(s, name=f"solid{i}")
    # save() は廃止予告 (FutureWarning) が出るので後継の export() を使う
    assy.export(step_path)
    print(f"STEP: {step_path}")

    model = CadToDagmc()
    model.add_stp_file(step_path, material_tags=tags)
    # h5m_backend は既定で "h5py"。pymoab を使わないのがこの検証の要点なので、
    # 既定に頼らず明示しておく (上流が既定を戻したら即座に気づけるように)。
    model.export_dagmc_h5m_file(filename=h5m_path, h5m_backend="h5py")
    print(f"h5m : {h5m_path}")

    # OpenMC が DAGMC ジオメトリとして読めるか。DAGMCUniverse.n_cells は h5py で
    # .h5m を直接読む。期待セル数 = ソリッド数 2 + 陰的補集合 1 (実行時に外側へ足される)
    u = openmc.DAGMCUniverse(h5m_path)
    print(f"n_cells={u.n_cells} n_surfaces={u.n_surfaces}")
    try:
        print(f"materials: {u.material_names}")
    except Exception as e:  # 材料名の取得は版によって挙動が違うので致命にしない
        print(f"materials: (取得不可: {e})")
    if u.n_cells != 3:
        print(f"FAIL: n_cells が不一致 (期待 3, 実際 {u.n_cells})")
        sys.exit(1)
    print("PASS: STEP → .h5m → OpenMC 読み込みが一気通貫で成立")


if __name__ == "__main__":
    main()
