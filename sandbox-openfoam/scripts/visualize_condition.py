#!/usr/bin/env python3
"""Hartmann ケースの計算領域と境界条件(流入・流出・壁面・周期)を 3D 図にする。

hartmann/system/blockMeshDict の領域 (x∈[0,10], y∈[-1,1], z∈[0,0.1]) と
0/{U,p,PotE} の境界条件に対応。z は薄いので表示上拡大している。

実行 (uv 経由、ホスト python に numpy が無いため):

    uv run --with numpy --with matplotlib scripts/visualize_condition.py --out out/boundary_conditions.png
"""

import argparse

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# blockMeshDict と同じ領域寸法
LX, Y0, Y1, LZ = 10.0, -1.0, 1.0, 0.1

COL_INLET = "tab:green"
COL_OUTLET = "tab:orange"
COL_WALL = "0.55"
COL_CYCLIC = "tab:blue"


def rect_x(x):
    """x = const 面 (流入・流出)"""
    return [(x, Y0, 0), (x, Y1, 0), (x, Y1, LZ), (x, Y0, LZ)]


def rect_y(y):
    """y = const 面 (壁)"""
    return [(0, y, 0), (LX, y, 0), (LX, y, LZ), (0, y, LZ)]


def rect_z(z):
    """z = const 面 (周期境界)"""
    return [(0, Y0, z), (LX, Y0, z), (LX, Y1, z), (0, Y1, z)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="出力 PNG パス")
    args = p.parse_args()

    fig = plt.figure(figsize=(9, 5))
    ax = fig.add_subplot(projection="3d")

    faces = [
        (rect_x(0), COL_INLET, 0.55),
        (rect_x(LX), COL_OUTLET, 0.55),
        (rect_y(Y0), COL_WALL, 0.45),
        (rect_y(Y1), COL_WALL, 0.45),
        (rect_z(0), COL_CYCLIC, 0.12),
        (rect_z(LZ), COL_CYCLIC, 0.12),
    ]
    for verts, color, alpha in faces:
        ax.add_collection3d(
            Poly3DCollection([verts], facecolor=color, edgecolor="k",
                             linewidths=0.6, alpha=alpha)
        )

    # 流入速度 (x 方向、一様)
    yq = np.array([-0.6, 0.0, 0.6])
    ax.quiver(np.full(3, -1.6), yq, np.full(3, LZ / 2),
              np.ones(3), np.zeros(3), np.zeros(3),
              length=1.4, color=COL_INLET, arrow_length_ratio=0.25, linewidth=2)
    ax.text(-1.9, 0, 0.28, r"$\mathbf{u}=(1,0,0)$", color=COL_INLET, fontsize=11)

    # 印加磁場 B0 (y 方向)。流路を貫く様子として複数本描く
    xb = np.array([4.5, 5.5])
    ax.quiver(xb, np.full(2, -1.9), np.full(2, LZ / 2),
              np.zeros(2), np.ones(2), np.zeros(2),
              length=3.8, color="tab:red", arrow_length_ratio=0.12, linewidth=2)
    ax.text(3.6, 1.7, 0.34, r"$\mathbf{B}_0=(0,\mathrm{Ha},0)$",
            color="tab:red", fontsize=11)

    # 誘導電流 J (z 方向、周期境界を通って閉じる)
    ax.quiver(7.5, 0, -0.13, 0, 0, 1,
              length=0.36, color=COL_CYCLIC, arrow_length_ratio=0.3, linewidth=2)
    ax.text(7.9, -0.9, 0.3, r"$\mathbf{J}\parallel z$ (cyclic)",
            color=COL_CYCLIC, fontsize=11)

    ax.set_xlabel("x (flow)")
    ax.set_ylabel("y (B0)")
    ax.set_zlabel("z")
    ax.set_xlim(-1.5, LX + 0.5)
    ax.set_ylim(-2.6, 2.6)
    ax.set_zlim(-0.15, 0.4)
    ax.set_box_aspect((5, 2.6, 1.3))
    ax.view_init(elev=22, azim=-60)
    ax.set_title("Hartmann case: domain and boundary conditions (z exaggerated)")

    legend_handles = [
        Patch(facecolor=COL_INLET, alpha=0.55,
              label=r"inlet ($x=0$): $\mathbf{u}=(1,0,0)$, "
                    r"$\partial p/\partial n=0$, $\partial\phi/\partial n=0$"),
        Patch(facecolor=COL_OUTLET, alpha=0.55,
              label=r"outlet ($x=10$): $\partial\mathbf{u}/\partial n=0$, "
                    r"$p=0$, $\partial\phi/\partial n=0$"),
        Patch(facecolor=COL_WALL, alpha=0.45,
              label=r"walls ($y=\pm 1$): $\mathbf{u}=0$ (no-slip), "
                    r"$\partial\phi/\partial n=0$ (insulating)"),
        Patch(facecolor=COL_CYCLIC, alpha=0.25,
              label="front/back ($z$): cyclic, 1 cell"),
    ]
    ax.legend(handles=legend_handles, loc="upper center",
              bbox_to_anchor=(0.5, -0.02), fontsize=9, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
