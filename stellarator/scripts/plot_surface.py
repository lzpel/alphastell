#!/usr/bin/env python3
"""VMEC 磁気面の点群 CSV を描画し、形状の妥当性を定量判定する。

入力は `cargo test` の export_point_cloud_csv が書く results/surface_points.csv
(列: s,i_phi,i_theta,phi,theta,R,Z,x,y,z,dR_dtheta,dZ_dtheta,dR_dphi,dZ_dphi)。

図は 3 パネル:

  1. s=1.00 の 3D 散布 (θ で着色) — 「点群が出た」という成果物そのもの
  2. φ = 0 / 半周期の半分 / 半周期 での (R,Z) 断面 — フーリエ評価が正しいことの
     定性的な指紋。微妙に壊れたリーダでも滑らかなトーラスは出るので、
     パネル 1 単独ではほぼ何も証明しない。ここが本命
  3. φ=0 での s=0.25/0.50/1.00/1.08 入れ子表示 + 磁気軸

判定 C1-C6 のうち C1 が最も強い。移植コードが一度も読まない netCDF 変数
(Rmajor_p / Aminor_p) と突き合わせるので、内部整合的だが誤ったフーリエ和は
通過できない。C5 (面の入れ子性) が s=1.08 で落ちた場合、それはバグではなく
「W2 のオフセットは素朴な s 外挿ではなく法線方向オフセットを要する」という
発見であり、閾値を緩めて通してはいけない。

参照値 (nfp, Rmajor_p, Aminor_p) は wout ファイルから直接読む。これらは VMEC が
書いたスカラー変数で、Rust の移植コードは一切読まない (rmnc/zmns/xm/xn だけ読む)
ので、点群との突き合わせは独立な検証であり続ける。

実行は uv 経由 (ホスト python に numpy/scipy が無いため):

    uv run --with numpy --with matplotlib --with scipy scripts/plot_surface.py \
      --csv results/surface_points.csv --wout out/wout_vmec.nc \
      --plot results/surface.png --report results/report.txt --tex results/values.tex
"""

import argparse
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from scipy.io import netcdf_file


def read_reference(path):
    """wout から nfp, Rmajor_p, Aminor_p を読む。VMEC が書いたスカラーで、
    Rust の移植 (rmnc/zmns/xm/xn しか読まない) とは独立。"""
    f = netcdf_file(path, mmap=False)
    nfp = int(f.variables["nfp"][()])
    rmajor = float(f.variables["Rmajor_p"][()])
    aminor = float(f.variables["Aminor_p"][()])
    return nfp, rmajor, aminor

TAU = 2.0 * np.pi


def load(path):
    """CSV を s ごとの (n_phi, n_theta) 格子 dict にまとめる。"""
    raw = np.genfromtxt(path, delimiter=",", names=True)
    out = {}
    for s in np.unique(raw["s"]):
        rows = raw[raw["s"] == s]
        n_phi = int(rows["i_phi"].max()) + 1
        n_theta = int(rows["i_theta"].max()) + 1
        # i_phi が外側、i_theta が内側の順で書かれている
        order = np.lexsort((rows["i_theta"], rows["i_phi"]))
        rows = rows[order]
        out[float(s)] = {
            name: rows[name].reshape(n_phi, n_theta) for name in raw.dtype.names
        }
    return out


def polygon_area_centroid(R, Z):
    """各 φ 断面 (閉多角形) の面積と R 方向重心を靴紐公式で返す。

    R, Z は (n_phi, n_theta)。θ は半開区間なので終点を折り返して閉じる。
    """
    r1, z1 = R, Z
    r2, z2 = np.roll(R, -1, axis=1), np.roll(Z, -1, axis=1)
    cross = r1 * z2 - r2 * z1
    signed_area = 0.5 * cross.sum(axis=1)
    r_c = ((r1 + r2) * cross).sum(axis=1) / (6.0 * signed_area)
    return np.abs(signed_area), r_c


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True, help="export_point_cloud_csv が出力した点群")
    p.add_argument("--wout", required=True, help="参照値 (nfp/Rmajor_p/Aminor_p) を読む wout ファイル")
    p.add_argument("--plot", required=True, help="出力 PNG パス")
    p.add_argument("--report", required=True, help="出力レポート (テキスト) パス")
    p.add_argument("--tex", help="LaTeX マクロ (\\newcommand) 出力パス")
    p.add_argument("--rtol-major", type=float, default=0.03, help="C1 大半径の相対許容")
    p.add_argument("--rtol-minor", type=float, default=0.05, help="C1 小半径の相対許容")
    p.add_argument("--tol-seam", type=float, default=1e-12, help="C3/C4 シーム閉合の許容 [m]")
    p.add_argument("--tol-period", type=float, default=1e-9, help="C2 周期対称性の許容 [m]")
    p.add_argument("--tol-deriv", type=float, default=1e-9, help="C6 導関数の相対許容 (スペクトル微分は厳密)")
    args = p.parse_args()

    g = load(args.csv)
    nfp, rmajor_ref, aminor_ref = read_reference(args.wout)
    lines = []
    fails = []

    def check(tag, ok, msg):
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {tag}: {msg}")
        if not ok:
            fails.append(f"{tag}: {msg}")

    lcfs = g[1.00]
    R, Z = lcfs["R"], lcfs["Z"]

    # --- C1: ファイル内の Rmajor_p / Aminor_p と突き合わせる (最強の判定) ---
    # VMEC の定義に合わせる。R の大域 max/min は使えない — ステラレータでは
    # 断面が φ とともに動くので、それは「断面の大きさ」ではなく
    # 「断面の移動幅を含んだ excursion」を測ってしまう。
    #   Aminor_p = sqrt(<A>/π)          A(φ) = 断面積 (φ 平均)
    #   Rmajor_p = V / (2π² Aminor_p²)  V = ∫∫∫ R dR dZ dφ = ∫ A(φ) R_c(φ) dφ
    area, r_centroid = polygon_area_centroid(R, Z)
    a_minor = np.sqrt(area.mean() / np.pi)
    volume = np.sum(area * r_centroid) * (TAU / R.shape[0])
    r_major = volume / (2.0 * np.pi**2 * a_minor**2)
    e_major = abs(r_major - rmajor_ref) / rmajor_ref
    e_minor = abs(a_minor - aminor_ref) / aminor_ref
    check(
        "C1 major radius",
        e_major < args.rtol_major,
        f"cloud {r_major:.4f} m vs wout {rmajor_ref:.4f} m (rel. {e_major:.2%})",
    )
    check(
        "C1 minor radius",
        e_minor < args.rtol_minor,
        f"cloud {a_minor:.4f} m vs wout {aminor_ref:.4f} m (rel. {e_minor:.2%})",
    )

    # --- C2: 磁場周期対称性。1 周期 = n_phi/nfp 行のシフト ---
    n_phi, n_theta = R.shape
    if n_phi % nfp:
        check("C2 field period", False, f"n_phi={n_phi} not divisible by nfp={nfp}")
        d_period = float("nan")
    else:
        shift = n_phi // nfp
        d_period = max(
            np.abs(R - np.roll(R, -shift, axis=0)).max(),
            np.abs(Z - np.roll(Z, -shift, axis=0)).max(),
        )
        check(
            "C2 field period",
            d_period < args.tol_period,
            f"phi -> phi + 2pi/{nfp}: max|delta| = {d_period:.3e} m",
        )

    # --- C3/C4: θ・φ シームの閉合。半開区間 [0,2π) sweep の契約 ---
    # 格子は端点を含まないので、周期境界での隣接差が内部の隣接差と同程度なら閉合している。
    def seam_gap(arr, axis):
        wrap = np.abs(np.roll(arr, -1, axis=axis) - arr).take(-1, axis=axis).max()
        inner = np.abs(np.diff(arr, axis=axis)).max()
        return wrap, inner

    for tag, axis in (("C3 theta seam", 1), ("C4 phi seam", 0)):
        wrap_r, inner_r = seam_gap(R, axis)
        wrap_z, inner_z = seam_gap(Z, axis)
        wrap, inner = max(wrap_r, wrap_z), max(inner_r, inner_z)
        check(
            tag,
            wrap <= inner * 1.5,
            f"wrap-around step {wrap:.3e} m vs max interior step {inner:.3e} m",
        )

    # --- C5: 面の入れ子性 ---
    # 「磁気軸からの距離が単調増加」では判定できない。bean 形状の断面では
    # 軸をどこに取っても距離が非単調になり得るため、正しく入れ子でも落ちる。
    # 断面多角形そのものの包含関係を見る。
    surfaces = sorted(g)
    from matplotlib.path import Path as MplPath

    nest_fail = []
    for a, b in zip(surfaces, surfaces[1:]):
        for i in range(n_phi):
            outer = MplPath(np.column_stack([g[b]["R"][i], g[b]["Z"][i]]))
            inner = np.column_stack([g[a]["R"][i], g[a]["Z"][i]])
            n_out = int((~outer.contains_points(inner)).sum())
            if n_out:
                nest_fail.append((a, b, i, n_out))
    if nest_fail:
        a, b, i, n_out = nest_fail[0]
        detail = (
            f"{len(nest_fail)} of {(len(surfaces) - 1) * n_phi} (surface, phi) pairs "
            f"not nested; first: s={a:.2f} escapes s={b:.2f} at i_phi={i} "
            f"({n_out}/{n_theta} points outside)"
        )
    else:
        detail = f"all {(len(surfaces) - 1) * n_phi} (surface, phi) pairs strictly nested"
    check("C5 nesting", not nest_fail, detail)

    # --- C6: 解析導関数 vs スペクトル微分 (θ 方向) ---
    # 有限差分は打ち切り誤差 O(dθ^p) が解析導関数の誤差を埋めてしまい判別力が無い
    # (mpol=11 の高波数では 4 次差分でも ~3e-3)。R(θ) は固定 (φ,s) では次数 mpol の
    # 三角多項式で、θ=48 点は帯域 (最大 xm=10 < Nyquist=24) を完全に解像している。
    # よって FFT によるスペクトル微分は丸め誤差まで厳密 — これと解析導関数が一致
    # すれば、解析 ∂R/∂θ の実装が正しいことを ~1e-10 級で独立に確認できる。
    k = np.fft.fftfreq(n_theta, d=1.0 / n_theta)  # 整数波数 0,1,...,-1
    spec = np.fft.ifft(1j * k * np.fft.fft(R, axis=1), axis=1).real
    scale = np.abs(lcfs["dR_dtheta"]).max()
    e_deriv = np.abs(spec - lcfs["dR_dtheta"]).max() / scale
    check(
        "C6 analytic derivative",
        e_deriv < args.tol_deriv,
        f"max|dR/dtheta - spectral| / max|dR/dtheta| = {e_deriv:.3e} "
        "(spectral deriv is exact for the resolved band)",
    )

    # ---------------- 図 ----------------
    fig = plt.figure(figsize=(16, 5.2))

    ax = fig.add_subplot(1, 3, 1, projection="3d")
    step = 2  # 見やすさのため間引く
    ax.scatter(
        lcfs["x"][::step, ::step],
        lcfs["y"][::step, ::step],
        lcfs["z"][::step, ::step],
        c=lcfs["theta"][::step, ::step],
        cmap="twilight",
        s=1.5,
    )
    ax.set_title(f"LCFS point cloud (s=1.00), nfp={nfp}")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_zlabel("z [m]")
    ax.set_box_aspect((1, 1, 0.45))

    ax = fig.add_subplot(1, 3, 2)
    half_period = n_phi // (2 * nfp)
    for idx, style in zip(
        (0, half_period // 2, half_period), ("-", "--", ":")
    ):
        phi_deg = np.degrees(lcfs["phi"][idx, 0])
        ax.plot(
            np.append(R[idx], R[idx][0]),
            np.append(Z[idx], Z[idx][0]),
            style,
            label=f"phi = {phi_deg:.1f} deg",
        )
    ax.set_aspect("equal")
    ax.set_title("LCFS cross-sections vs phi (shape change = fingerprint)")
    ax.set_xlabel("R [m]")
    ax.set_ylabel("Z [m]")
    ax.legend()
    ax.grid(alpha=0.3)

    ax = fig.add_subplot(1, 3, 3)
    for s in surfaces:
        r = g[s]["R"][0]
        z = g[s]["Z"][0]
        ax.plot(np.append(r, r[0]), np.append(z, z[0]), label=f"s = {s:.2f}")
    ax.plot(r_centroid[0], Z[0].mean(), "k+", markersize=10, label="axis (approx.)")
    ax.set_aspect("equal")
    ax.set_title("Nested surfaces at phi=0 (s=1.08 = W2 offset surface)")
    ax.set_xlabel("R [m]")
    ax.set_ylabel("Z [m]")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(args.plot, dpi=150)

    # ---------------- レポート ----------------
    header = [
        f"point cloud:   {args.csv}",
        f"surfaces:      {', '.join(f'{s:.2f}' for s in surfaces)}",
        f"grid:          {n_phi} (phi) x {n_theta} (theta)",
        f"wout metadata: Rmajor_p={rmajor_ref:.4f} m, Aminor_p={aminor_ref:.4f} m, nfp={nfp}",
        "",
    ]
    text = "\n".join(header + lines) + "\n"
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(text)
    print(text, end="")

    if args.tex:
        with open(args.tex, "w", encoding="utf-8") as f:
            f.write("% plot_surface.py --tex による自動生成。手で編集しない。\n")
            f.write(f"\\newcommand{{\\Rmajor}}{{{r_major:.4f}}}\n")
            f.write(f"\\newcommand{{\\aminor}}{{{a_minor:.4f}}}\n")
            f.write(f"\\newcommand{{\\RmajorErrPct}}{{{e_major * 100:.2f}}}\n")
            f.write(f"\\newcommand{{\\aminorErrPct}}{{{e_minor * 100:.2f}}}\n")
            f.write(f"\\newcommand{{\\periodErr}}{{{d_period:.2e}}}\n")
            f.write(f"\\newcommand{{\\nestFailures}}{{{len(nest_fail)}}}\n")
            f.write(f"\\newcommand{{\\plasmaVolume}}{{{volume:.2f}}}\n")
            f.write(f"\\newcommand{{\\derivErr}}{{{e_deriv:.2e}}}\n")
            f.write(f"\\newcommand{{\\nfp}}{{{nfp}}}\n")

    if fails:
        sys.exit("FAIL: " + "; ".join(fails))


if __name__ == "__main__":
    main()
