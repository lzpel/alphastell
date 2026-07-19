#!/usr/bin/env python3
"""検証体系 (リチウム球 + 中心 14.1 MeV 等方点線源) の模式図を描く。

model.py のジオメトリ (半径 R の CSG 球、等体積球シェル分割) と線源に対応。
中性子が磁場を受けないこと、輸送に要るのは形状と材料だけであることを図で示す。

実行 (uv 経由、ホスト python に numpy が無いため):

    uv run --with numpy --with matplotlib scripts/visualize_condition.py --out results/condition.png --radius 20
"""

import argparse

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def shell_edges(radius, n):
    return radius * (np.arange(n + 1) / n) ** (1.0 / 3.0)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="出力 PNG パス")
    p.add_argument("--radius", type=float, default=20.0, help="球半径 [cm]")
    p.add_argument("--shells", type=int, default=8, help="模式図に描くシェル数 (実行時とは別、見やすさ優先)")
    args = p.parse_args()

    R = args.radius
    fig, ax = plt.subplots(figsize=(6.4, 6.0))

    # 球本体
    body = plt.Circle((0, 0), R, facecolor="tab:blue", alpha=0.10,
                      edgecolor="tab:blue", linewidth=2, zorder=1)
    ax.add_patch(body)

    # 等体積シェル (タリー区画)
    for r in shell_edges(R, args.shells)[1:-1]:
        ax.add_patch(plt.Circle((0, 0), r, fill=False, edgecolor="tab:blue",
                                linewidth=0.5, alpha=0.5, linestyle="--", zorder=2))

    # 中心の点線源から等方に飛ぶ中性子 (直進 = 未衝突トラック)
    ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    for a in ang:
        ax.plot([0, R * np.cos(a)], [0, R * np.sin(a)], color="tab:red",
                linewidth=0.8, alpha=0.5, zorder=3)
    ax.plot(0, 0, "*", color="tab:red", ms=18, zorder=4,
            label="14.1 MeV isotropic point source")

    # 注記 (matplotlib に CJK フォントを仮定しないため英語/mathtext)
    ax.annotate("Li sphere (natural)\nvacuum boundary", xy=(R * 0.62, R * 0.62),
                xytext=(R * 0.72, R * 0.98), fontsize=10, color="tab:blue")
    ax.annotate(r"$\phi(r)=\dfrac{S\,e^{-\Sigma_t r}}{4\pi r^2}$",
                xy=(R * 0.5, 0), xytext=(-R * 1.02, -R * 1.10),
                fontsize=13)
    ax.annotate("", xy=(R, 0), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="k", lw=1.2))
    ax.text(R * 0.5, R * 0.05, "r", fontsize=12)
    ax.text(R * 0.5, -R * 0.10, f"R = {R:g} cm", fontsize=10, ha="center")

    ax.set_xlim(-R * 1.15, R * 1.15)
    ax.set_ylim(-R * 1.25, R * 1.20)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Verification system: central point source + Li sphere (CSG, no CAD)\n"
                 "neutrons ignore the magnetic field: transport needs only shape and material",
                 fontsize=10)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
