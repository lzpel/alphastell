# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "matplotlib",
#     "numpy",
#     "pandas",
# ]
# ///
"""Visualize chamber point cloud from generate (--output <dir>/chamber_points.csv).

Produces a 4-panel diagnostic PNG: 3D scatter, top view, poloidal cross-sections
highlighting the phi=0/2π seam, and step-size continuity at the seam.

Usage (via make view):
    uv run tools/view_chamber.py --input out/chamber_points.csv --output out/chamber_view.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers 3D projection


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="out/chamber_points.csv", help="CSV from generate")
    ap.add_argument("--output", default="out/chamber_view.png", help="PNG output path")
    ap.add_argument("--show", action="store_true", help="also open an interactive window")
    args = ap.parse_args()

    df = pd.read_csv(args.input)
    m = int(df["phi_idx"].max()) + 1
    n = int(df["theta_idx"].max()) + 1
    assert len(df) == m * n, f"expected {m*n} rows, got {len(df)}"
    print(f"loaded {len(df)} points: {m} phi × {n} theta")

    # Reshape into (phi_idx, theta_idx) grids
    xs = df["x"].values.reshape(m, n)
    ys = df["y"].values.reshape(m, n)
    zs = df["z"].values.reshape(m, n)
    theta = df["theta_rad"].values.reshape(m, n)[0, :]
    rs = np.sqrt(xs**2 + ys**2)

    fig = plt.figure(figsize=(16, 12))

    # --- 1. 3D scatter (color = phi_idx) ---
    ax1 = fig.add_subplot(2, 2, 1, projection="3d")
    phi_color = np.repeat(np.arange(m), n)
    ax1.scatter(xs.ravel(), ys.ravel(), zs.ravel(), c=phi_color, s=2, cmap="hsv")
    ax1.set_title("3D scatter (color = phi_idx)")
    ax1.set_xlabel("X [m]")
    ax1.set_ylabel("Y [m]")
    ax1.set_zlabel("Z [m]")

    # --- 2. Top view (X, Y) — seam at phi=0 would show as a kink in the toroidal ring ---
    ax2 = fig.add_subplot(2, 2, 2)
    sc = ax2.scatter(xs.ravel(), ys.ravel(), c=phi_color, s=3, cmap="hsv")
    # Highlight seam-edge rows
    ax2.plot(xs[0], ys[0], "r-", lw=1.5, label=f"phi_idx=0 (phi=0)")
    ax2.plot(xs[m - 1], ys[m - 1], "b-", lw=1.5, label=f"phi_idx={m-1} (phi≈2π)")
    ax2.set_aspect("equal")
    ax2.set_title("Top view (X, Y) — seam rows overlaid")
    ax2.set_xlabel("X [m]")
    ax2.set_ylabel("Y [m]")
    ax2.legend()
    plt.colorbar(sc, ax=ax2, label="phi_idx")

    # --- 3. Poloidal cross-sections (R, Z) — seam vs interior ---
    ax3 = fig.add_subplot(2, 2, 3)
    # faint: all cross-sections
    for i in range(m):
        rr = np.append(rs[i], rs[i, 0])
        zz = np.append(zs[i], zs[i, 0])
        ax3.plot(rr, zz, color="lightgray", lw=0.3)
    mid = m // 2
    for idx, color, label in [
        (0, "red", f"phi_idx=0"),
        (m - 1, "blue", f"phi_idx={m-1}"),
        (mid, "green", f"phi_idx={mid}"),
    ]:
        rr = np.append(rs[idx], rs[idx, 0])
        zz = np.append(zs[idx], zs[idx, 0])
        ax3.plot(rr, zz, color=color, lw=1.5, marker="o", markersize=3, label=label)
    ax3.set_aspect("equal")
    ax3.set_xlabel("R = √(x²+y²) [m]")
    ax3.set_ylabel("Z [m]")
    ax3.set_title("Poloidal cross-sections (all faint; seam rows highlighted)")
    ax3.legend()

    # --- 4. Step size at the seam vs typical — should be comparable if periodic ---
    ax4 = fig.add_subplot(2, 2, 4)
    # Distance between adjacent-in-phi points, theta by theta
    d_seam = np.sqrt(
        (xs[0] - xs[m - 1]) ** 2 + (ys[0] - ys[m - 1]) ** 2 + (zs[0] - zs[m - 1]) ** 2
    )
    d_typical = np.sqrt(
        (xs[m - 1] - xs[m - 2]) ** 2
        + (ys[m - 1] - ys[m - 2]) ** 2
        + (zs[m - 1] - zs[m - 2]) ** 2
    )
    ax4.plot(theta, d_typical, "g-", label=f"|p[{m-1}]-p[{m-2}]| (interior step)")
    ax4.plot(theta, d_seam, "r-", label=f"|p[0]-p[{m-1}]| (seam step)")
    ax4.set_xlabel("theta [rad]")
    ax4.set_ylabel("3D distance [m]")
    ax4.set_title("phi-step size at seam vs interior (should overlap for periodic data)")
    ax4.legend()

    plt.tight_layout()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=120)
    print(f"wrote {out}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
