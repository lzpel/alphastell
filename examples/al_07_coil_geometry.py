#!/usr/bin/env python3
"""VMEC の LCFS を再現するモジュラーコイルを simsopt の stage-2 最適化で起こす (al_07)。

手法は optimize() にある。main() はそれをコイル-プラズマ距離について走査し、
CSV・3D 図・PDF レポート (本文は al_07_report.typ) を出すだけの段取りである。

al_06 で PbLi 殻を厚くするほど TBR が上がると分かったが、厚みを置く空間はコイルが決める。
距離を振って磁気面の再現誤差を見ると、ブランケット・遮蔽・真空容器に使える半径方向の予算が出る。

    make al-07
"""

import math
import pathlib
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import typst
from scipy.io import netcdf_file
from scipy.optimize import minimize
from simsopt.field import BiotSavart, Current, coils_via_symmetries
from simsopt.geo import CurveCurveDistance, CurveLength, CurveSurfaceDistance, LpCurveCurvature, MeanSquaredCurvature, SurfaceRZFourier, create_equally_spaced_curves
from simsopt.objectives import QuadraticPenalty, SquaredFlux

MU0 = 4e-7 * math.pi


def optimize(
	surface: SurfaceRZFourier, standoff: float, ncoils: int, order: int, b0: float, length_target: float,
	cc_threshold: float, curvature_threshold: float, msc_threshold: float, weights: dict[str, float], maxiter: int,
) -> dict[str, Any]:
	"""磁気面を固定してコイルだけを動かす stage-2。standoff はコイル-プラズマ距離の要求値 [m]。

	1. 磁気軸のまわりに ncoils 本の円環を等間隔に置く (半周期ぶん)
	2. 正味ポロイダル電流だけを固定し、各コイルの電流は自由にする
	3. stellarator 対称と nfp 回転で 2*nfp*ncoils 本に増やす
	4. 目的関数 = 規格化 B·n の二乗積分 + 長さ/コイル間/プラズマ間/曲率のペナルティ
	5. L-BFGS-B で解く

	閾値 (length_target 等) は工学的な制約そのもの、weights は物理的意味を持たない数値の重み。
	"""
	nfp = surface.nfp
	r_major = surface.get_rc(0, 0)
	base_curves = create_equally_spaced_curves(ncoils, nfp, stellsym=True, R0=r_major, R1=3.5 + standoff, order=order)

	# 正味ポロイダル電流 2πR·B0/μ0 を半周期に配り、その合計だけを固定する。
	# 最後の 1 本を「合計 - 残り」にすると本数分の自由度から 1 つだけ減る。
	half_period_current = 2 * math.pi * r_major * b0 / MU0 / (2 * nfp)
	base_currents = [Current(half_period_current / ncoils * 1e-5) * 1e5 for _ in range(ncoils - 1)]
	fixed_total = Current(half_period_current)
	fixed_total.fix_all()
	base_currents.append(fixed_total - sum(base_currents))

	coils = coils_via_symmetries(base_curves, base_currents, nfp, True)
	field = BiotSavart(coils)
	field.set_points(surface.gamma().reshape((-1, 3)))

	# definition="local" は ∫(B·n/|B|)² dA。無次元なので重みが b0 の仮定に引きずられない。
	flux = SquaredFlux(surface, field, definition="local")
	lengths = [CurveLength(c) for c in base_curves]
	distance_cc = CurveCurveDistance([c.curve for c in coils], cc_threshold, num_basecurves=ncoils)
	distance_cs = CurveSurfaceDistance(base_curves, surface, standoff)
	objective = (
		flux
		+ weights["length"] * sum(QuadraticPenalty(length, length_target, "max") for length in lengths)
		+ weights["cc"] * distance_cc
		+ weights["cs"] * distance_cs
		+ weights["curvature"] * sum(LpCurveCurvature(c, 2, curvature_threshold) for c in base_curves)
		+ weights["msc"] * sum(QuadraticPenalty(MeanSquaredCurvature(c), msc_threshold, "max") for c in base_curves)
	)

	def fun(dofs: np.ndarray) -> tuple[float, np.ndarray]:
		objective.x = dofs
		return objective.J(), objective.dJ()

	minimize(fun, objective.x, jac=True, method="L-BFGS-B", options={"maxiter": maxiter, "maxcor": 300})

	# B·n/|B| を (φ, θ) 格子の形で。0 なら磁気面がコイルの作る磁場と整合する。
	b = field.B().reshape(surface.gamma().shape)
	return {
		"standoff": standoff,
		"coils": coils,
		"error": (b * surface.unitnormal()).sum(axis=-1) / np.linalg.norm(b, axis=-1),
		"lengths": [float(length.J()) for length in lengths],
		"currents": [float(current.get_value()) for current in base_currents],
		"radii": [1.0 / float(np.max(c.kappa())) for c in base_curves],
		"cc": float(distance_cc.shortest_distance()),
		"cs": float(distance_cs.shortest_distance()),
	}


def make_surface(harmonics: dict[str, Any], quadpoints_phi: np.ndarray, quadpoints_theta: np.ndarray) -> SurfaceRZFourier:
	"""LCFS を simsopt の SurfaceRZFourier にする。

	VMEC も simsopt も R = Σ rc cos(mθ - n·nfp·φ) なので、xn を nfp で割るだけで移せる。
	"""
	nfp, xm, xn = harmonics["nfp"], harmonics["xm"], harmonics["xn"]
	surface = SurfaceRZFourier(
		nfp=nfp,
		stellsym=True,
		mpol=int(xm.max()),
		ntor=int(np.abs(xn).max()) // nfp,
		quadpoints_phi=quadpoints_phi,
		quadpoints_theta=quadpoints_theta,
	)
	for m, n, rc, zs in zip(xm, xn, harmonics["rmnc"], harmonics["zmns"]):
		surface.set_rc(m, n // nfp, rc)
		surface.set_zs(m, n // nfp, zs)
	return surface


def fourier_coefficients(points: np.ndarray, order: int) -> tuple[np.ndarray, np.ndarray]:
	"""周期点列 (t = 0..1 の等間隔) を三角多項式の係数に戻す。

	x(t) = Σ_m [ c_m cos(2πmt) + s_m sin(2πmt) ]。曲線は order 次の帯域制限なので
	FFT で厳密に取れる。点列より係数の方が、下流で任意の分解能の滑らかな CAD を引ける。
	対称操作の像も回転行列を掛けただけで次数は変わらないため、同じ扱いでよい。
	"""
	spectrum = np.fft.rfft(points, axis=0) / len(points)
	cosine, sine = 2 * spectrum.real, -2 * spectrum.imag
	cosine[0] /= 2
	return cosine[: order + 1], sine[: order + 1]


def main(
	wout: pathlib.Path, out: pathlib.Path, standoffs: list[float], ncoils: int, order: int, nphi: int, ntheta: int,
	b0: float, length_target: float, cc_threshold: float, curvature_threshold: float, msc_threshold: float,
	weights: dict[str, float], maxiter: int,
) -> list[dict[str, Any]]:
	with netcdf_file(wout, mmap=False) as f:
		harmonics = {
			"nfp": int(f.variables["nfp"][()]),
			"xm": f.variables["xm"][:].astype(int),
			"xn": f.variables["xn"][:].astype(int),
			"rmnc": f.variables["rmnc"][-1],  # 最外殻 = LCFS
			"zmns": f.variables["zmns"][-1],
		}
	nfp = harmonics["nfp"]
	surface = make_surface(harmonics, np.linspace(0, 1 / (2 * nfp), nphi, endpoint=False), np.linspace(0, 1, ntheta, endpoint=False))

	results = []
	for standoff in standoffs:
		result = optimize(surface, standoff, ncoils, order, b0, length_target, cc_threshold, curvature_threshold, msc_threshold, weights, maxiter)
		results.append(result)
		print(
			f"standoff {standoff:.1f} m: max |B.n|/|B| = {np.abs(result['error']).max():.2e}, "
			f"achieved {result['cs']:.2f} m, coil-coil {result['cc']:.2f} m, length {sum(result['lengths']) * 2 * nfp:.0f} m"
		)
	baseline = results[0]
	coils = baseline["coils"]

	# --- コイル形状を Fourier 係数で書き出す。下流の CAD/構造解析はここから読む ---------
	out.mkdir(parents=True, exist_ok=True)
	geometry = [coil.curve.gamma() for coil in coils]
	rows = []
	for index, (coil, points) in enumerate(zip(coils, geometry)):
		cosine, sine = fourier_coefficients(points, order)
		mode = np.arange(order + 1)
		angle = math.tau * np.outer(np.linspace(0, 1, len(points), endpoint=False), mode)
		assert np.allclose(np.cos(angle) @ cosine + np.sin(angle) @ sine, points), "fourier fit is not exact"
		rows.append(np.column_stack([np.full(order + 1, index), np.full(order + 1, coil.current.get_value()), mode, cosine, sine]))
	np.savetxt(
		out / "al_07_coils.csv", np.concatenate(rows), delimiter=",",
		header="coil,current_A,m,xc,yc,zc,xs,ys,zs", comments="", fmt="%.9e",  # 係数の単位は m
	)

	# --- 図 ----------------------------------------------------------------------------
	colors = plt.get_cmap("tab10")
	wall = make_surface(harmonics, np.linspace(0, 1, 120), np.linspace(0, 1, 48)).gamma()  # 端点を含めて φ, θ の継ぎ目を閉じる
	figure = plt.figure(figsize=(11, 5.5))
	axes = figure.add_subplot(projection="3d")
	axes.plot_surface(
		wall[..., 0], wall[..., 1], wall[..., 2],
		color="#b8bec7", alpha=0.30, rstride=1, cstride=1, linewidth=0, edgecolor="none", antialiased=False, shade=True,
	)
	# 独立コイルは ncoils 本だけで、残りは stellarator 対称と nfp 回転の像。色をその index で振る。
	for index, points in enumerate(geometry):
		loop = np.concatenate([points, points[:1]])
		axes.plot(loop[:, 0], loop[:, 1], loop[:, 2], color=colors(index % ncoils), linewidth=1.5)
	# トーラスは扁平なので軸ごとの実寸比を保たないと形が嘘になる
	axes.set_box_aspect((np.ptp(wall[..., 0]), np.ptp(wall[..., 1]), np.ptp(wall[..., 2])), zoom=1.5)
	axes.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
	axes.zaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
	axes.view_init(elev=38, azim=-55)
	axes.grid(False)
	for pane in (axes.xaxis, axes.yaxis, axes.zaxis):
		pane.pane.set_alpha(0.0)
	axes.set_title(
		f"modular coils from stage-2 optimization: {len(coils)} coils ({ncoils} unique x {2 * nfp} symmetry images)\n"
		f"coil-plasma {baseline['cs']:.2f} m, max |B.n|/|B| = {np.abs(baseline['error']).max():.1e}, "
		f"total length {sum(baseline['lengths']) * 2 * nfp:.0f} m"
	)
	figure.savefig(out / "al_07_coils.png", dpi=150, bbox_inches="tight")
	plt.close(figure)

	figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.0))
	mesh = left.pcolormesh(
		np.linspace(0, 360 / (2 * nfp), nphi), np.linspace(0, 360, ntheta), baseline["error"].T,
		cmap="coolwarm", norm=matplotlib.colors.CenteredNorm(), shading="nearest",
	)
	figure.colorbar(mesh, ax=left, label="B.n / |B|")
	left.set(xlabel="phi [deg]", ylabel="theta [deg]", title=f"normal field error, coil-plasma {baseline['cs']:.2f} m")
	right.semilogy([r["cs"] for r in results], [np.abs(r["error"]).max() for r in results], marker="o", label="max")
	right.semilogy([r["cs"] for r in results], [np.abs(r["error"]).mean() for r in results], marker="x", linestyle="--", label="mean")
	# al_06 の PbLi 最大厚み。この線とデータ点の差が第一壁・真空容器・遮蔽に使える残りになる
	right.axvline(0.7, color="#c0392b", linestyle=":", linewidth=1.2)
	right.text(0.72, right.get_ylim()[0] * 1.3, "al_06 PbLi 70 cm", fontsize=8, color="#c0392b")
	right.set(xlabel="achieved coil-plasma distance [m]", ylabel="|B.n| / |B|", title="how far the coils can back off")
	right.legend()
	right.grid(alpha=0.3)
	figure.tight_layout()
	figure.savefig(out / "al_07_error.png", dpi=150, bbox_inches="tight")
	plt.close(figure)

	# --- PDF レポート。本文は隣の al_07_report.typ にあり、ここでは数値だけ差し込む -------
	fields = {
		"nfp": nfp, "r_major": surface.get_rc(0, 0), "ncoils": ncoils, "order": order, "b0": b0,
		"ncoils_total": len(coils), "nimages": 2 * nfp, "maxiter": maxiter,
		"length_target": length_target, "cc_threshold": cc_threshold,
		"curvature_threshold": curvature_threshold, "bend_radius": 1 / curvature_threshold,
		"standoff_min": standoffs[0], "standoff_max": standoffs[-1],
		"cs_first": baseline["cs"], "cs_last": results[-1]["cs"],
		"cc_first": baseline["cc"], "cc_last": results[-1]["cc"],
		"error_first": np.abs(baseline["error"]).max(), "error_last": np.abs(results[-1]["error"]).max(),
		"coil_rows": "".join(
			f"  [{i}], [{baseline['lengths'][i]:.1f}], [{baseline['currents'][i] / 1e6:.2f}], [{baseline['radii'][i]:.2f}],\n"
			for i in range(ncoils)
		),
		"scan_rows": "".join(
			f"  [{r['standoff']:.1f}], [{r['cs']:.2f}], [{np.abs(r['error']).max():.1e}], [{np.abs(r['error']).mean():.1e}], "
			f"[{sum(r['lengths']) * 2 * nfp:.0f}], [{r['cc']:.2f}],\n"
			for r in results
		),
	}
	template = pathlib.Path(__file__).with_name("al_07_report.typ").read_text(encoding="utf-8")
	(out / "al_07_report.typ").write_text(template.format(**fields), encoding="utf-8")
	typst.compile(out / "al_07_report.typ", output=out / "al_07_report.pdf")
	print(f"{out / 'al_07_report.pdf'}: {(out / 'al_07_report.pdf').stat().st_size} bytes")
	return results


if __name__ == "__main__":
	main(
		wout=pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc",
		out=pathlib.Path("out"),
		standoffs=[1.5, 2.0, 2.5, 3.0],  # コイル-プラズマ最小距離の要求値 [m]。先頭を 3D 図と CSV に出す
		ncoils=4,  # 半周期あたりの独立コイル数。全体では 2*nfp*ncoils 個
		order=6,  # コイル 1 本の Fourier 次数。上げると細かく波打つ
		nphi=32,  # B·n を評価する半周期の格子
		ntheta=32,
		b0=5.5,  # 境界の平均大半径での磁場 [T]。電流の絶対値を決めるためだけの仮定
		length_target=32.0,  # コイル 1 本の長さ上限 [m]
		cc_threshold=0.8,  # コイル間の最小距離 [m]
		curvature_threshold=0.5,  # 曲率上限 [1/m]。最小曲げ半径 2 m
		msc_threshold=0.25,  # 平均二乗曲率の上限 [1/m^2]。局所的でない波打ちを抑える
		weights={"length": 1e-3, "cc": 3e-1, "cs": 3e-2, "curvature": 1e-2, "msc": 1e-2},
		maxiter=300,
	)
