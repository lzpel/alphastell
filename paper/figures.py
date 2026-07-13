"""Mock figures for the draft preprint. Every dataset here is synthetic.

Run from the paper/ directory:
    docker run --rm -v .:/work -w /work python:3.12-slim \
        sh -c "pip install matplotlib numpy && python figures.py"
Replace with production data extraction before submission.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

rng = np.random.default_rng(20260714)
DPI = 200


def fig01_dp_map():
    """Mock MHD pressure-gradient map on the unrolled (theta, phi) surface."""
    theta = np.linspace(0, 2 * np.pi, 200)
    phi = np.linspace(0, 2 * np.pi / 5, 200)  # one field period, N_fp = 5
    T, P = np.meshgrid(theta, phi)
    # Synthetic |B|^2-like pattern: bean-section peaks + toroidal ripple
    dp = (
        1.0
        + 0.55 * np.cos(T) ** 2 * (1 + 0.4 * np.cos(5 * P))
        + 0.25 * np.cos(2 * T - 5 * P)
    )
    dp *= 0.9  # scale to ~MPa/m
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    im = ax.pcolormesh(np.degrees(P), np.degrees(T), dp.T, cmap="inferno", shading="auto")
    fig.colorbar(im, ax=ax, label=r"$\mathrm{d}p/\mathrm{d}x$ [MPa/m] (mock)")
    ax.set_xlabel(r"toroidal angle $\phi$ [deg]")
    ax.set_ylabel(r"poloidal angle $\theta$ [deg]")
    ax.set_title("MOCK: MHD pressure-gradient distribution, one field period")
    fig.tight_layout()
    fig.savefig("fig01.png", dpi=DPI)
    plt.close(fig)


def fig02_hartmann():
    """Analytic Hartmann profile vs synthetic 'CFD' markers."""
    Ha = 20.0
    y = np.linspace(-1, 1, 400)
    u = (np.cosh(Ha) - np.cosh(Ha * y)) / (np.cosh(Ha) - np.sinh(Ha) / Ha)
    y_cfd = np.linspace(-1, 1, 25)
    u_cfd = (np.cosh(Ha) - np.cosh(Ha * y_cfd)) / (np.cosh(Ha) - np.sinh(Ha) / Ha)
    u_cfd *= 1 + rng.normal(0, 0.008, y_cfd.size)  # mock discretisation error
    fig, ax = plt.subplots(figsize=(4.8, 3.6))
    ax.plot(y, u, "-", color="#1f4e79", label=f"analytic, Ha = {Ha:.0f}")
    ax.plot(y_cfd, u_cfd, "o", ms=4, mfc="none", color="#c0392b", label="anchoring CFD (mock)")
    ax.set_xlabel(r"$y / L$")
    ax.set_ylabel(r"$u / u_0$")
    ax.set_title("MOCK: Hartmann-flow validation")
    ax.legend()
    fig.tight_layout()
    fig.savefig("fig02.png", dpi=DPI)
    plt.close(fig)


def fig03_pareto():
    """Mock design population and Pareto front: TBR vs pumping-power fraction."""
    n = 60
    f_pump = 10 ** rng.uniform(-0.7, 0.9, n)  # 0.2 .. 8 %
    # TBR rises with pumping cost (thinner/faster channels breed worse), saturating
    tbr = 1.02 + 0.16 * (1 - np.exp(-f_pump / 1.5)) + rng.normal(0, 0.015, n)
    pts = sorted(zip(f_pump, tbr))
    front_x, front_y, best = [], [], -np.inf
    for x, yv in pts:
        if yv > best:
            front_x.append(x)
            front_y.append(yv)
            best = yv
    fig, ax = plt.subplots(figsize=(4.8, 3.6))
    ax.scatter(f_pump, tbr, s=18, color="#7f8c8d", alpha=0.7, label="sampled layouts (mock)")
    ax.plot(front_x, front_y, "o-", color="#1f4e79", ms=5, label="Pareto front (mock)")
    ax.axhline(1.10, color="#c0392b", ls="--", lw=1, label="TBR = 1.10 requirement")
    ax.set_xscale("log")
    ax.set_xticks([0.2, 0.5, 1, 2, 5])
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_xlabel(r"pumping-power fraction $f_\mathrm{pump}$ [%]")
    ax.set_ylabel("TBR")
    ax.set_title("MOCK: TBR vs pumping-power trade-off")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig("fig03.png", dpi=DPI)
    plt.close(fig)


if __name__ == "__main__":
    fig01_dp_map()
    fig02_hartmann()
    fig03_pareto()
    print("wrote fig01.png fig02.png fig03.png")
