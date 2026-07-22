#!/usr/bin/env python3
"""epotFoam の Hartmann 流速度プロファイルを解析解と比較する。

解析解 (Hartmann 1937, 非導体壁, バルク速度正規化, 半幅 a=1):

    u(y)/u_bulk = Ha/(Ha - tanh(Ha)) * (1 - cosh(Ha*y)/cosh(Ha))

実行は uv 経由 (ホスト python に numpy が無いため):

    uv run --with numpy --with matplotlib compare_hartmann.py --ha 20 --profile <xy>
"""

import argparse
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

trapezoid = getattr(np, "trapezoid", None) or np.trapz


def hartmann_profile(y, ha):
    """バルク正規化 Hartmann 速度分布。cosh 比は指数形で計算し Ha~10^3 でも桁溢れしない。"""
    # cosh(ha*y)/cosh(ha) = (exp(ha*(y-1)) + exp(-ha*(y+1))) / (1 + exp(-2*ha))
    ratio = (np.exp(ha * (y - 1.0)) + np.exp(-ha * (y + 1.0))) / (1.0 + np.exp(-2.0 * ha))
    return ha / (ha - np.tanh(ha)) * (1.0 - ratio)


def bulk(u, y):
    return trapezoid(u, y) / (y[-1] - y[0])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ha", type=float, required=True, help="Hartmann 数")
    p.add_argument("--profile", required=True, help="raw 形式サンプル (列: y Ux Uy Uz)")
    p.add_argument("--plot", required=True, help="出力 PNG パス")
    p.add_argument("--report", required=True, help="出力レポート (テキスト) パス")
    p.add_argument("--threshold", type=float, default=0.02, help="合格閾値 (最大相対誤差)")
    p.add_argument("--tex", help="LaTeX マクロ (\\newcommand) 出力パス。レポート原稿が \\input して数値を参照する")
    args = p.parse_args()

    data = np.loadtxt(args.profile)
    y, ux = data[:, 0], data[:, 1]

    # 数値解・解析解ともサンプル区間のバルク速度で正規化して比較する
    # (サンプル区間が壁ぎわ 0.1% を欠くバイアスを両者対称に除去)
    u_num = ux / bulk(ux, y)
    u_ana = hartmann_profile(y, args.ha)
    u_ana = u_ana / bulk(u_ana, y)

    err = (u_num - u_ana) / u_ana.max()
    max_err = float(np.max(np.abs(err)))
    rms_err = float(np.sqrt(np.mean(err**2)))
    ok = max_err <= args.threshold

    lines = [
        f"Hartmann flow validation  (Ha = {args.ha:g})",
        f"profile:            {args.profile}",
        f"points:             {len(y)}",
        f"bulk velocity (raw): {bulk(ux, y):.6f}",
        f"core velocity  num/ana: {u_num[np.argmin(np.abs(y))]:.6f} / {u_ana[np.argmin(np.abs(y))]:.6f}",
        f"max |rel. error|:   {max_err * 100:.3f} %   (threshold {args.threshold * 100:g} %)",
        f"RMS rel. error:     {rms_err * 100:.3f} %",
        f"result:             {'PASS' if ok else 'FAIL'}",
    ]
    report = "\n".join(lines) + "\n"
    with open(args.report, "w") as f:
        f.write(report)
    print(report, end="")

    if args.tex:
        i0 = int(np.argmin(np.abs(y)))
        macros = [
            r"% compare_hartmann.py --tex による自動生成。手で編集しない。",
            rf"\newcommand{{\HaVal}}{{{args.ha:g}}}",
            rf"\newcommand{{\maxErrPct}}{{{max_err * 100:.3f}}}",
            rf"\newcommand{{\rmsErrPct}}{{{rms_err * 100:.3f}}}",
            rf"\newcommand{{\coreNum}}{{{u_num[i0]:.5f}}}",
            rf"\newcommand{{\coreAna}}{{{u_ana[i0]:.5f}}}",
            rf"\newcommand{{\bulkRaw}}{{{bulk(ux, y):.6f}}}",
            rf"\newcommand{{\thresholdPct}}{{{args.threshold * 100:g}}}",
        ]
        with open(args.tex, "w") as f:
            f.write("\n".join(macros) + "\n")

    y_dense = np.linspace(y[0], y[-1], 1000)
    u_dense = hartmann_profile(y_dense, args.ha)
    u_dense = u_dense / bulk(u_dense, y_dense)

    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.plot(y_dense, u_dense, "-", color="tab:blue", label=f"analytic (Ha={args.ha:g})")
    ax.plot(
        y[::4], u_num[::4], "o", mfc="none", color="tab:red", ms=5, label="epotFoam"
    )
    ax.set_xlabel("y / a")
    ax.set_ylabel(r"$u_x\,/\,\bar{u}$")
    ax.set_title("Hartmann flow: epotFoam vs analytic solution")
    ax.legend(loc="lower center")
    ax.text(
        0.02,
        0.02,
        f"max err {max_err * 100:.2f}%\nRMS err {rms_err * 100:.2f}%",
        transform=ax.transAxes,
        fontsize=9,
        va="bottom",
        bbox=dict(boxstyle="round", fc="white", alpha=0.7),
    )
    fig.tight_layout()
    fig.savefig(args.plot, dpi=150)

    if not ok:
        sys.exit(f"FAIL: max relative error {max_err * 100:.3f}% > {args.threshold * 100:g}%")


if __name__ == "__main__":
    main()
