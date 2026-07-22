#!/usr/bin/env python3
"""環状先細ダクト MHD ケースの検証とプロファイル図生成。

解析解が無いため、次を検証する:
  1. 質量保存: |Q_in + Q_out| / |Q_in| < threshold (phi の面積分、非ゼロ終了で FAIL)
  2. 定常性: 最終時刻と1つ前の書き出しのプロファイル一致
  3. 図: 入口/出口 × B平行(+y)/B垂直(+z) の軸方向速度プロファイル
     (Hartmann 層と側層の θ 異方性の可視化)

実行: uv run --with numpy --with matplotlib scripts/verify_cone.py --case cone ...
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def last_value(dat_path):
    """surfaceFieldValue.dat の最終行の値 (time, value)"""
    rows = [l.split() for l in open(dat_path) if not l.startswith("#")]
    t, v = rows[-1][0], rows[-1][1]
    return float(t), float(v)


def read_profile(case, time, name):
    data = np.loadtxt(f"{case}/postProcessing/sample/{time}/{name}_U.xy")
    return data[:, 0], data[:, 1]  # distance, Ux


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", default="cone")
    p.add_argument("--ha", type=float, required=True)
    p.add_argument("--plot", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--tex", help="LaTeX マクロ出力")
    p.add_argument("--threshold", type=float, default=1e-6, help="質量保存の相対誤差閾値")
    args = p.parse_args()

    # ---- 質量保存 ----
    def dat(name):
        d = sorted(Path(f"{args.case}/postProcessing/{name}").iterdir())[0]
        return d / "surfaceFieldValue.dat"

    _, q_in = last_value(dat("fluxInlet"))
    _, q_out = last_value(dat("fluxOutlet"))
    _, p_in = last_value(dat("pInlet"))
    mass_err = abs(q_in + q_out) / abs(q_in)
    mass_ok = mass_err <= args.threshold

    # ---- プロファイル (最終時刻と1つ前で定常性確認) ----
    times = sorted((Path(args.case) / "postProcessing/sample").iterdir(), key=lambda d: float(d.name))
    t_last, t_prev = times[-1].name, times[-2].name
    names = ["inletParaB", "inletPerpB", "outletParaB", "outletPerpB"]
    steady_err = 0.0
    for n in names:
        _, u1 = read_profile(args.case, t_prev, n)
        _, u2 = read_profile(args.case, t_last, n)
        m = min(len(u1), len(u2))
        steady_err = max(steady_err, float(np.max(np.abs(u1[:m] - u2[:m]))))
    steady_ok = steady_err < 1e-2

    lines = [
        f"annular converging duct verification  (Ha = {args.ha:g})",
        f"flux inlet / outlet:  {q_in:+.8f} / {q_out:+.8f}",
        f"mass conservation:    |Qin+Qout|/|Qin| = {mass_err:.3e}  (threshold {args.threshold:g})",
        f"steadiness (t={t_prev} vs {t_last}): max |dU| = {steady_err:.3e}",
        f"inlet area-avg p:     {p_in:.6f}  (outlet p = 0)",
        f"result:               {'PASS' if (mass_ok and steady_ok) else 'FAIL'}",
    ]
    report = "\n".join(lines) + "\n"
    with open(args.report, "w") as f:
        f.write(report)
    print(report, end="")

    # ---- 図 ----
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, station, title in [
        (axes[0], "inlet", "inlet (x=0.5)"),
        (axes[1], "outlet", "outlet (x=4.5)"),
    ]:
        for name, style, label in [
            (f"{station}ParaB", "-", r"ray $\parallel \mathbf{B}_0$ (+y)"),
            (f"{station}PerpB", "--", r"ray $\perp \mathbf{B}_0$ (+z)"),
        ]:
            s, ux = read_profile(args.case, t_last, name)
            ax.plot(s, ux, style, label=label)
        ax.set_xlabel("distance from inner wall")
        ax.set_title(title)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel(r"$u_x$")
    axes[0].legend()
    fig.suptitle(f"Annular converging duct, Ha={args.ha:g}: axial velocity profiles")
    fig.tight_layout()
    fig.savefig(args.plot, dpi=150)

    if args.tex:
        def tex_sci(x):
            if x == 0.0:
                return "0"  # 厳密にゼロ (機械精度で一致)
            m, e = f"{x:.1e}".split("e")
            return rf"{m}\times10^{{{int(e)}}}"

        # 出口プロファイルの最大値 (増速の指標)
        _, u_out_perp = read_profile(args.case, t_last, "outletPerpB")
        _, u_in_perp = read_profile(args.case, t_last, "inletPerpB")
        macros = [
            r"% verify_cone.py --tex による自動生成。手で編集しない。",
            rf"\newcommand{{\HaCone}}{{{args.ha:g}}}",
            rf"\newcommand{{\massErr}}{{{tex_sci(mass_err)}}}",
            rf"\newcommand{{\steadyErr}}{{{tex_sci(steady_err)}}}",
            rf"\newcommand{{\fluxIn}}{{{abs(q_in):.4f}}}",
            rf"\newcommand{{\dpCone}}{{{p_in:.3f}}}",
            rf"\newcommand{{\uMaxIn}}{{{u_in_perp.max():.3f}}}",
            rf"\newcommand{{\uMaxOut}}{{{u_out_perp.max():.3f}}}",
        ]
        with open(args.tex, "w") as f:
            f.write("\n".join(macros) + "\n")

    if not (mass_ok and steady_ok):
        sys.exit(f"FAIL: mass_err={mass_err:.3e} steady_err={steady_err:.3e}")


if __name__ == "__main__":
    main()
