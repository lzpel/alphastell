#!/usr/bin/env python3
"""OpenMC の未衝突中性子束を輸送方程式の厳密解と比較する。

体系は 14.1 MeV 等方点線源 (強度 S) を中心に置いた半径 R のリチウム球。
未衝突成分は厳密に解けて、束の空間分布は

    phi(r) = S * exp(-Sigma_t * r) / (4 * pi * r^2)

Sigma_t は 14.1 MeV での巨視的全断面積 (単一の数)。未衝突中性子はエネルギーを
変えないので、これは近似ではなく厳密解である。

球シェル [r1, r2] の体積平均束も厳密:

    <phi> = ∫phi dV / V = S * (exp(-Sigma_t*r1) - exp(-Sigma_t*r2)) / (Sigma_t * V)

タリーもシェル平均束なので、r 中心の点値ではなくこの体積平均と比較する
(ビン化バイアスを避ける)。判定は決定論の Hartmann と違い統計誤差 sigma を持つので、
「最大相対誤差 < 閾値」に加えて「相対誤差が 3σ を超えるシェルが無い」を併用する。

実行は uv 経由 (ホスト python に numpy が無いため):

    uv run --with numpy --with matplotlib compare_attenuation.py \
      --tally out/tally.json --xs out/xs.json --plot ... --report ... --tex ...
"""

import argparse
import json
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def shell_average_analytic(edges, sigma_t, strength):
    """球シェル体積平均の未衝突束 [1/cm^2/src]。厳密。"""
    r1 = edges[:-1]
    r2 = edges[1:]
    vol = (4.0 / 3.0) * np.pi * (r2**3 - r1**3)
    return strength * (np.exp(-sigma_t * r1) - np.exp(-sigma_t * r2)) / (sigma_t * vol)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tally", required=True, help="model.py が出力した out/tally.json")
    p.add_argument("--xs", required=True, help="model.py が出力した out/xs.json")
    p.add_argument("--plot", required=True, help="出力 PNG パス")
    p.add_argument("--report", required=True, help="出力レポート (テキスト) パス")
    p.add_argument("--threshold", type=float, default=0.02, help="合格閾値 (最大相対誤差)")
    p.add_argument("--nsigma", type=float, default=3.0, help="統計的許容 (相対誤差 < nsigma*σ)")
    p.add_argument("--tex", help="LaTeX マクロ (\\newcommand) 出力パス")
    args = p.parse_args()

    with open(args.tally) as f:
        t = json.load(f)
    with open(args.xs) as f:
        xs = json.load(f)

    edges = np.array(t["shell_edges"])
    r_mid = 0.5 * (edges[:-1] + edges[1:])
    sigma_t = xs["sigma_t"]
    strength = t["source_strength"]

    phi_num = np.array(t["uncollided_flux"])
    phi_sd = np.array(t["uncollided_flux_sd"])
    phi_ana = shell_average_analytic(edges, sigma_t, strength)

    # 相対誤差は解析解を分母にする (各シェルの絶対値が桁で変わるため)。
    rel = (phi_num - phi_ana) / phi_ana
    max_err = float(np.max(np.abs(rel)))
    rms_err = float(np.sqrt(np.mean(rel**2)))

    # 統計的整合: 各シェルで |num-ana| が nsigma*σ 以内か。
    with np.errstate(divide="ignore", invalid="ignore"):
        zscore = np.abs(phi_num - phi_ana) / phi_sd
    n_outlier = int(np.sum(np.nan_to_num(zscore, nan=0.0) > args.nsigma))

    # 参考: 表面漏洩 L と初回衝突総数 C の厳密解 (未衝突)。
    leak_ana = strength * np.exp(-sigma_t * t["radius"])
    coll_ana = strength * (1.0 - np.exp(-sigma_t * t["radius"]))

    ok = (max_err <= args.threshold) and (n_outlier == 0)

    lines = [
        f"Uncollided-flux attenuation validation  (R = {t['radius']:g} cm)",
        f"tally:              {args.tally}",
        f"library:            {xs['library']}",
        f"openmc:             {xs.get('openmc_version', '?')}",
        f"Sigma_t(14.1 MeV):  {sigma_t:.6e} /cm   (mfp {1.0 / sigma_t:.4f} cm)",
        f"shells:             {len(r_mid)}   particles/batch: {t['particles']}",
        f"max |rel. error|:   {max_err * 100:.3f} %   (threshold {args.threshold * 100:g} %)",
        f"RMS rel. error:     {rms_err * 100:.3f} %",
        f"shells > {args.nsigma:g}sigma:      {n_outlier}",
        f"leakage (analytic): {leak_ana:.6e} per source neutron",
        f"first-collisions:   {coll_ana:.6e} per source neutron  (analytic)",
        f"TBR (reference):    {t['tbr']:.5f} +/- {t['tbr_sd']:.5f}",
        f"result:             {'PASS' if ok else 'FAIL'}",
    ]
    report = "\n".join(lines) + "\n"
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report)
    print(report, end="")

    if args.tex:
        macros = [
            r"% compare_attenuation.py --tex による自動生成。手で編集しない。",
            rf"\newcommand{{\radiusCm}}{{{t['radius']:g}}}",
            rf"\newcommand{{\SigmaT}}{{{sigma_t:.4f}}}",
            rf"\newcommand{{\meanFreePath}}{{{1.0 / sigma_t:.3f}}}",
            rf"\newcommand{{\shellsN}}{{{len(r_mid)}}}",
            rf"\newcommand{{\particlesN}}{{{t['particles']:,}}}".replace(",", r"{,}"),
            rf"\newcommand{{\maxErrPct}}{{{max_err * 100:.3f}}}",
            rf"\newcommand{{\rmsErrPct}}{{{rms_err * 100:.3f}}}",
            rf"\newcommand{{\nOutlier}}{{{n_outlier}}}",
            rf"\newcommand{{\nSigma}}{{{args.nsigma:g}}}",
            rf"\newcommand{{\leakAna}}{{{leak_ana:.4e}}}",
            rf"\newcommand{{\collAna}}{{{coll_ana:.4e}}}",
            rf"\newcommand{{\tbrVal}}{{{t['tbr']:.4f}}}",
            rf"\newcommand{{\tbrUnc}}{{{t['tbr_sd']:.4f}}}",
            rf"\newcommand{{\thresholdPct}}{{{args.threshold * 100:g}}}",
        ]
        with open(args.tex, "w", encoding="utf-8") as f:
            f.write("\n".join(macros) + "\n")

    # --- プロット: 4*pi*r^2*phi vs r の片対数 → 直線 (傾き -Sigma_t) ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))

    # 左: 束そのもの (両対数)
    ax1.errorbar(r_mid, phi_num, yerr=phi_sd, fmt="o", mfc="none",
                 color="tab:red", ms=5, label="OpenMC (uncollided)", capsize=2)
    r_dense = np.linspace(edges[1] * 0.5, edges[-1], 400)
    phi_dense = strength * np.exp(-sigma_t * r_dense) / (4.0 * np.pi * r_dense**2)
    ax1.plot(r_dense, phi_dense, "-", color="tab:blue", label="analytic")
    ax1.set_yscale("log")
    ax1.set_xlabel("r [cm]")
    ax1.set_ylabel(r"$\phi(r)$  [1/cm$^2$/src]")
    ax1.set_title("Uncollided flux")
    ax1.legend()

    # 右: 4*pi*r^2*phi = S*exp(-Sigma_t*r) → 片対数で直線
    ax2.semilogy(r_mid, 4.0 * np.pi * r_mid**2 * phi_num, "o", mfc="none",
                 color="tab:red", ms=5, label="OpenMC")
    ax2.semilogy(r_dense, strength * np.exp(-sigma_t * r_dense), "-",
                 color="tab:blue", label=rf"$S\,e^{{-\Sigma_t r}}$, $\Sigma_t$={sigma_t:.4f}")
    ax2.set_xlabel("r [cm]")
    ax2.set_ylabel(r"$4\pi r^2 \phi(r)$  [1/cm/src]")
    ax2.set_title("Attenuation (semilog straight line)")
    ax2.legend()
    ax2.text(0.03, 0.03, f"max err {max_err * 100:.2f}%\nRMS {rms_err * 100:.2f}%\n>{args.nsigma:g}σ: {n_outlier}",
             transform=ax2.transAxes, fontsize=9, va="bottom",
             bbox=dict(boxstyle="round", fc="white", alpha=0.7))

    fig.tight_layout()
    fig.savefig(args.plot, dpi=150)

    if not ok:
        sys.exit(f"FAIL: max rel err {max_err * 100:.3f}% (thr {args.threshold * 100:g}%), "
                 f"{n_outlier} shells > {args.nsigma:g}sigma")


if __name__ == "__main__":
    main()
