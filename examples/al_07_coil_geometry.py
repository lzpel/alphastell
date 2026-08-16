#!/usr/bin/env python3
"""VMEC の LCFS を再現するモジュラーコイルを simsopt の stage-2 最適化で起こす (al_07)。

手法は optimize_coil() にある。main() はそれをコイル-プラズマ距離について走査し、
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

MU0 = 4e-7 * math.pi


def make_surface(
	wout: pathlib.Path, # VMEC の平衡出力 (wout*.nc)。最外殻の Fourier 係数だけを読む
	quadpoints_phi: np.ndarray | None = None, # トロイダル角の評価点。既定は半周期 0..1/(2*nfp) の 32 点
	quadpoints_theta: np.ndarray | None = None, # ポロイダル角の評価点。既定は一周 0..1 の 32 点
) -> SurfaceRZFourier:
	"""LCFS を simsopt の SurfaceRZFourier にする。

	VMEC も simsopt も R = Σ rc cos(mθ - n·nfp·φ) なので、xn を nfp で割るだけで移せる。
	格子の単位は回転数 (1.0 = 全周) でラジアンではない。既定は B·n の評価用で、
	周期領域の継ぎ目を二重に数えないよう端点を含めない。3D 図のように継ぎ目を
	閉じたい場合は端点込みの配列を渡す。
	"""
	from simsopt.geo import SurfaceRZFourier
	from scipy.io import netcdf_file

	with netcdf_file(wout, mmap=False) as f:
		nfp = int(f.variables["nfp"][()])
		xm = f.variables["xm"][:].astype(int)
		xn = f.variables["xn"][:].astype(int)
		rmnc = f.variables["rmnc"][-1]  # 最外殻 = LCFS
		zmns = f.variables["zmns"][-1]

	if quadpoints_phi is None:
		quadpoints_phi = np.linspace(0, 1 / (2 * nfp), 32, endpoint=False)
	if quadpoints_theta is None:
		quadpoints_theta = np.linspace(0, 1, 32, endpoint=False)

	surface = SurfaceRZFourier(
		nfp=nfp,
		stellsym=True,
		mpol=int(xm.max()),
		ntor=int(np.abs(xn).max()) // nfp,
		quadpoints_phi=quadpoints_phi,
		quadpoints_theta=quadpoints_theta,
	)
	for m, n, rc, zs in zip(xm, xn, rmnc, zmns):
		surface.set_rc(m, n // nfp, rc)
		surface.set_zs(m, n // nfp, zs)
	return surface


def optimize_coil(
	surface: SurfaceRZFourier, # 固定する LCFS。この面上の B·n を消すようにコイルが動く
	standoff: float, # コイル-プラズマ距離の要求値 [m]。ペナルティの閾値と初期半径の両方に効く
	ncoils: int, # 半周期あたりの独立コイル数。全体では 2*nfp*ncoils 本になる
	order: int, # コイル 1 本の Fourier 次数。自由度は 1 本あたり 3*(2*order+1) 個
	b0: float, # 大半径での磁場 [T]。正味ポロイダル電流の総量を決めるためだけに使う
	length_target: float, # コイル 1 本の長さ上限 [m]。超えた分だけ二次で罰する
	cc_threshold: float, # コイル間の最小距離 [m]。組み立てと支持構造が要求する
	curvature_threshold: float, # 曲率上限 [1/m]。逆数が導体の最小曲げ半径
	msc_threshold: float, # 平均二乗曲率の上限 [1/m^2]。曲率上限では拾えない全体の波打ちを抑える
	weights: dict[str, float], # 各ペナルティの重み。キーは length/curve_curve_distance/curve_surface_distance/curvature/msc
	maxiter: int, # L-BFGS-B の反復上限
) -> dict[str, Any]:
	"""磁気面を固定してコイルだけを動かす stage-2。

	1. 磁気軸のまわりに ncoils 本の円環を等間隔に置く (半周期ぶん)
	2. 正味ポロイダル電流だけを固定し、各コイルの電流は自由にする
	3. stellarator 対称と nfp 回転で 2*nfp*ncoils 本に増やす
	4. 目的関数 = 規格化 B·n の二乗積分 + 長さ/コイル間/プラズマ間/曲率のペナルティ
	5. L-BFGS-B で解く

	閾値 (length_target 等) は工学的な制約そのもの、weights は物理的意味を持たない数値の重み。
	"""
	from simsopt.field import BiotSavart, Current, coils_via_symmetries
	from simsopt.geo import CurveCurveDistance, CurveLength, CurveSurfaceDistance, LpCurveCurvature, MeanSquaredCurvature, create_equally_spaced_curves
	from simsopt.objectives import QuadraticPenalty, SquaredFlux
	from scipy.optimize import minimize
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
	# flux + 重み * 罰
	objective = (
		flux
		+ weights["length"] * sum(QuadraticPenalty(length, length_target, "max") for length in lengths)
		+ weights["curve_curve_distance"] * distance_cc
		+ weights["curve_surface_distance"] * distance_cs
		+ weights["curvature"] * sum(LpCurveCurvature(c, 2, curvature_threshold) for c in base_curves)
		+ weights["msc"] * sum(QuadraticPenalty(MeanSquaredCurvature(c), msc_threshold, "max") for c in base_curves)
	)

	# 目的関数の値と勾配を返す
	def fun(dofs: np.ndarray) -> tuple[float, np.ndarray]:
		objective.x = dofs
		return objective.J(), objective.dJ()

	minimize(fun, objective.x, jac=True, method="L-BFGS-B", options={"maxiter": maxiter, "maxcor": 300})

	# B·n/|B| を (φ, θ) 格子の形で。0 なら磁気面がコイルの作る磁場と整合する。
	b = field.B().reshape(surface.gamma().shape)
	

	def fourier_coefficients(points: np.ndarray, order: int) -> np.ndarray:
		"""周期点列 (t = 0..1 の等間隔) を三角多項式の係数 [3, 2*order+1] に戻す。x(t) = Σ_m [ c_m cos(2πmt) + s_m sin(2πmt) ]。列は simsopt の DOF と同じ [c_0, s_1, c_1, .. s_order, c_order]"""
		spectrum = np.fft.rfft(points, axis=0)[: order + 1] / len(points)
		# stack で s_m, c_m を交互に並べ、先頭の [s_0, c_0] だけ落として c_0 を単独で戻す
		return np.concatenate([spectrum[:1].real, np.stack([-2 * spectrum.imag, 2 * spectrum.real], 1).reshape(-1, 3)[2:]]).T
	return {
		# 入力の要求値をそのまま返す。実際に到達した距離は "curve_surface_distance"
		"standoff": standoff,
		# 対称像も含めた全 2*nfp*ncoils 本。3D 図と CSV はここから引く
		"coils": coils,
		# coils と同じ順序のフーリエ係数 [3, 2*order+1]。対称像 (RotatedCurve) は自前の DOF を持たず x を読むと回転前の係数が返るので、全本を gamma() から一様に起こす
		"coeffs": np.array([fourier_coefficients(coil.curve.gamma(), order) for coil in coils]),
		# B·n/|B| を (phi, theta) 格子で。符号付きの無次元量で、0 なら磁気面と整合する
		"error": (b * surface.unitnormal()).sum(axis=-1) / np.linalg.norm(b, axis=-1),
		# 独立コイル ncoils 本の周長 [m]。装置全体の導体長は 2*nfp 倍する
		"lengths": [float(length.J()) for length in lengths],
		# 独立コイル ncoils 本の電流 [A]。最後の 1 本は総量を固定するための従属変数
		"currents": [float(current.get_value()) for current in base_currents],
		# 独立コイル ncoils 本の最小曲げ半径 [m] = 1/max(κ)。導体の曲げ許容と比べる
		"radii": [1.0 / float(np.max(c.kappa())) for c in base_curves],
		# 以下 2 つは閾値ではなく最適化後の実測値。罰則が効いたかをこれで確認する
		"curve_curve_distance": float(distance_cc.shortest_distance()),  # コイル間の最小距離 [m]
		"curve_surface_distance": float(distance_cs.shortest_distance()),  # コイル-プラズマ最小距離 [m]
	}


def main(
	wout: pathlib.Path, out: pathlib.Path, standoffs: list[float], ncoils: int, order: int,
	b0: float, length_target: float, cc_threshold: float, curvature_threshold: float, msc_threshold: float,
	weights: dict[str, float], maxiter: int,
) -> list[dict[str, Any]]:
	surface = make_surface(wout)
	nfp = surface.nfp

	results = []
	for standoff in standoffs:
		result = optimize_coil(surface, standoff, ncoils, order, b0, length_target, cc_threshold, curvature_threshold, msc_threshold, weights, maxiter)
		results.append(result)
		print(
			f"standoff {standoff:.1f} m: max |B.n|/|B| = {np.abs(result['error']).max():.2e}, "
			f"achieved {result['curve_surface_distance']:.2f} m, coil-coil {result['curve_curve_distance']:.2f} m, length {sum(result['lengths']) * 2 * nfp:.0f} m"
		)
	baseline = results[0]
	coils = baseline["coils"]

	# --- コイル形状を Fourier 係数で書き出す。下流の CAD/構造解析はここから読む ---------
	out.mkdir(parents=True, exist_ok=True)
	geometry = [coil.curve.gamma() for coil in coils]
	rows = []
	for index, (coil, coefficients) in enumerate(zip(coils, baseline["coeffs"])):
		# CSV は m ごとに 1 行なので、cos 側と sin 側を並べ直す。sin の m=0 は定義上ゼロ
		cosine = coefficients[:, 0::2].T
		sine = np.vstack([np.zeros(3), coefficients[:, 1::2].T])
		rows.append(np.column_stack([np.full(order + 1, index), np.full(order + 1, coil.current.get_value()), np.arange(order + 1), cosine, sine]))
	np.savetxt(
		out / "al_07_coils.csv", np.concatenate(rows), delimiter=",",
		header="coil,current_A,m,xc,yc,zc,xs,ys,zs", comments="", fmt="%.9e",  # 係数の単位は m
	)

	# --- 図 ----------------------------------------------------------------------------
	colors = plt.get_cmap("tab10")
	wall = make_surface(wout, np.linspace(0, 1, 120), np.linspace(0, 1, 48)).gamma()  # 端点を含めて φ, θ の継ぎ目を閉じる
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
		f"coil-plasma {baseline['curve_surface_distance']:.2f} m, max |B.n|/|B| = {np.abs(baseline['error']).max():.1e}, "
		f"total length {sum(baseline['lengths']) * 2 * nfp:.0f} m"
	)
	figure.savefig(out / "al_07_coils.png", dpi=150, bbox_inches="tight")
	plt.close(figure)

	figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.0))
	mesh = left.pcolormesh(
		surface.quadpoints_phi * 360, surface.quadpoints_theta * 360, baseline["error"].T,
		cmap="coolwarm", norm=matplotlib.colors.CenteredNorm(), shading="nearest",
	)
	figure.colorbar(mesh, ax=left, label="B.n / |B|")
	left.set(xlabel="phi [deg]", ylabel="theta [deg]", title=f"normal field error, coil-plasma {baseline['curve_surface_distance']:.2f} m")
	right.semilogy([r["curve_surface_distance"] for r in results], [np.abs(r["error"]).max() for r in results], marker="o", label="max")
	right.semilogy([r["curve_surface_distance"] for r in results], [np.abs(r["error"]).mean() for r in results], marker="x", linestyle="--", label="mean")
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
		"cs_first": baseline["curve_surface_distance"], "cs_last": results[-1]["curve_surface_distance"],
		"cc_first": baseline["curve_curve_distance"], "cc_last": results[-1]["curve_curve_distance"],
		"error_first": np.abs(baseline["error"]).max(), "error_last": np.abs(results[-1]["error"]).max(),
		"coil_rows": "".join(
			f"  [{i}], [{baseline['lengths'][i]:.1f}], [{baseline['currents'][i] / 1e6:.2f}], [{baseline['radii'][i]:.2f}],\n"
			for i in range(ncoils)
		),
		"scan_rows": "".join(
			f"  [{r['standoff']:.1f}], [{r['curve_surface_distance']:.2f}], [{np.abs(r['error']).max():.1e}], [{np.abs(r['error']).mean():.1e}], "
			f"[{sum(r['lengths']) * 2 * nfp:.0f}], [{r['curve_curve_distance']:.2f}],\n"
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
		b0=5.5,  # 境界の平均大半径での磁場 [T]。電流の絶対値を決めるためだけの仮定
		length_target=32.0,  # コイル 1 本の長さ上限 [m]
		cc_threshold=0.8,  # コイル間の最小距離 [m]
		curvature_threshold=0.5,  # 曲率上限 [1/m]。最小曲げ半径 2 m
		msc_threshold=0.25,  # 平均二乗曲率の上限 [1/m^2]。局所的でない波打ちを抑える
		weights={"length": 1e-3, "curve_curve_distance": 3e-1, "curve_surface_distance": 3e-2, "curvature": 1e-2, "msc": 1e-2},
		maxiter=300,
	)
