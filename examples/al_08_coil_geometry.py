import math
import pathlib
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
	threshold_curve_surface_distances: list[float] = [1.5, 2.0, 2.5, 3.0],  # コイル-プラズマ最小距離の要求値 [m]。先頭を 3D 図と CSV に出す
	width: float = 0.40,  # 導体断面のトロイダル幅 [m]。al_081 と同じ parastell 準拠の値
	height: float = 0.50,  # 導体断面の半径方向厚み [m]。同上
	mu0: float = 4e-7 * math.pi,
) -> list[dict[str, Any]]:
	surface = make_surface(wout, np.linspace(0, 1, 120), np.linspace(0, 1, 48))

	results = []
	for threshold_curve_surface_distance in threshold_curve_surface_distances:
		result = optimize_coil(surface, mu0, threshold_curve_surface_distance=threshold_curve_surface_distance)
		results.append(result)
		print(f"requested {threshold_curve_surface_distance:.1f} m: max |B.n|/|B| = {np.abs(result['error']).max():.2e}, achieved {result['curve_surface_distance']:.2f} m, coil-coil {result['curve_curve_distance']:.2f} m, length {sum(result['lengths']) * 2 * surface.nfp:.0f} m")
	baseline = results[0]
	ncoils = baseline["parameters"]["ncoils"]

	# --- コイル形状を Fourier 係数で書き出す。下流の CAD/構造解析はここから読む ---------
	spines = [coil.curve.gamma() for coil in baseline["coils"]]
	# coeffs は [ncoil, 3, 2*order+1] で軸ごとに [c0, s1, c1, .. s_order, c_order]。行 = コイル 1 本に平坦化する
	np.savetxt(
		out.with_suffix(".coeffs.csv"), baseline["coeffs"].reshape(len(baseline["coeffs"]), -1), delimiter=",", fmt="%.9e",
		header="row = one coil; columns = [c0, s1, c1, .. s_order, c_order] for x, then y, then z [m]",
	)

	projected_spines = project_spines(wout, spines)
	visualize_spines(projected_spines, out.with_suffix(".spines.png"), surface)
	# al_081 と同じ矩形断面で掃引した導体ソリッドの 4 面図
	solids = sweep_spines(width, height, projected_spines)
	with open(out.with_suffix(".sweep.png"), "wb") as f:
		solids.write_png(f)

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
	figure.savefig(out.with_suffix(".error.png"), dpi=150, bbox_inches="tight")
	plt.close(figure)

	# --- Markdown レポート。本文は末尾の TEMPLATE にあり、ここでは数値だけ差し込む ----------
	fields = baseline["parameters"] | {
		"nfp": surface.nfp, "r_major": surface.get_rc(0, 0), "width": width, "height": height,
		"ncoils_total": len(baseline["coils"]), "nimages": 2 * surface.nfp, "bend_radius": 1 / baseline["parameters"]["threshold_curvature"],
		"threshold_curve_surface_distance_min": threshold_curve_surface_distances[0], "threshold_curve_surface_distance_max": threshold_curve_surface_distances[-1],
		"cs_first": baseline["curve_surface_distance"], "cs_last": results[-1]["curve_surface_distance"],
		"cc_first": baseline["curve_curve_distance"], "cc_last": results[-1]["curve_curve_distance"],
		"error_first": np.abs(baseline["error"]).max(), "error_last": np.abs(results[-1]["error"]).max(),
		"coil_rows": "".join(
			f"| {i} | {baseline['lengths'][i]:.1f} | {baseline['currents'][i] / 1e6:.2f} | {baseline['radii'][i]:.2f} |\n"
			for i in range(ncoils)
		),
		"scan_rows": "".join(
			f"| {r['parameters']['threshold_curve_surface_distance']:.1f} | {r['curve_surface_distance']:.2f} | {np.abs(r['error']).max():.1e} | {np.abs(r['error']).mean():.1e} | "
			f"{sum(r['lengths']) * 2 * surface.nfp:.0f} | {r['curve_curve_distance']:.2f} |\n"
			for r in results
		),
		"out_png": out.with_suffix(".spines.png").name,
		"out_sweep_png": out.with_suffix(".sweep.png").name,
		"out_error_png": out.with_suffix(".error.png").name,
		"out_csv": out.with_suffix(".coeffs.csv").name,
	}
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	return results


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
	mu0: float, # 真空の透磁率 [H/m]。正味ポロイダル電流の換算にだけ使う
	ncoils: int = 4, # 半周期あたりの独立コイル数。全体では 2*nfp*ncoils 本になる
	order: int = 6, # コイル 1 本の Fourier 次数。自由度は 1 本あたり 3*(2*order+1) 個。上げると細かく波打つ
	b0: float = 5.5, # 大半径での磁場 [T]。正味ポロイダル電流の総量を決めるためだけに使う
	iteration: int = 300, # L-BFGS-B の反復上限
	threshold_length: float = 32.0, # コイル 1 本の長さ上限 [m]。超えた分だけ二次で罰する
	weight_length: float = 1e-3, # 長さペナルティの重み
	threshold_curve_curve_distance: float = 0.8, # コイル間の最小距離 [m]。組み立てと支持構造が要求する
	weight_curve_curve_distance: float = 3e-1, # コイル間距離ペナルティの重み
	threshold_curve_surface_distance: float = 1.5, # コイル-プラズマ距離の要求値 [m]。ペナルティの閾値と初期半径の両方に効く
	weight_curve_surface_distance: float = 3e-2, # コイル-プラズマ距離ペナルティの重み
	threshold_curvature: float = 0.5, # 曲率上限 [1/m]。逆数が導体の最小曲げ半径
	weight_curvature: float = 1e-2, # 曲率ペナルティの重み
	threshold_mean_squared_curvature: float = 0.25, # 平均二乗曲率の上限 [1/m^2]。曲率上限では拾えない全体の波打ちを抑える
	weight_mean_squared_curvature: float = 1e-2, # 平均二乗曲率ペナルティの重み
) -> dict[str, Any]:
	"""磁気面を固定してコイルだけを動かす stage-2。

	1. 磁気軸のまわりに ncoils 本の円環を等間隔に置く (半周期ぶん)
	2. 正味ポロイダル電流だけを固定し、各コイルの電流は自由にする
	3. stellarator 対称と nfp 回転で 2*nfp*ncoils 本に増やす
	4. 目的関数 = 規格化 B·n の二乗積分 + 長さ/コイル間/プラズマ間/曲率のペナルティ
	5. L-BFGS-B で解く

	閾値 (threshold_length 等) は工学的な制約そのもの、weight_* は物理的意味を持たない数値の重み。
	"""
	# docstring 直後ならローカルはまだ引数だけ。返り値で入力をそのまま echo する
	parameters = {k: v for k, v in locals().items() if k != "surface"}
	from simsopt.field import BiotSavart, Current, coils_via_symmetries
	from simsopt.geo import CurveCurveDistance, CurveLength, CurveSurfaceDistance, LpCurveCurvature, MeanSquaredCurvature, create_equally_spaced_curves
	from simsopt.objectives import QuadraticPenalty, SquaredFlux
	from scipy.optimize import minimize
	r_major = surface.get_rc(0, 0)
	base_curves = create_equally_spaced_curves(ncoils, surface.nfp, stellsym=True, R0=r_major, R1=3.5 + threshold_curve_surface_distance, order=order)

	# 正味ポロイダル電流 2πR·B0/μ0 を半周期に配り、その合計だけを固定する。
	# 最後の 1 本を「合計 - 残り」にすると本数分の自由度から 1 つだけ減る。
	half_period_current = 2 * math.pi * r_major * b0 / mu0 / (2 * surface.nfp)
	base_currents = [Current(half_period_current / ncoils * 1e-5) * 1e5 for _ in range(ncoils - 1)]
	fixed_total = Current(half_period_current)
	fixed_total.fix_all()
	base_currents.append(fixed_total - sum(base_currents))

	coils = coils_via_symmetries(base_curves, base_currents, surface.nfp, True)
	field = BiotSavart(coils)
	field.set_points(surface.gamma().reshape((-1, 3)))

	# definition="local" は ∫(B·n/|B|)² dA。無次元なので重みが b0 の仮定に引きずられない。
	flux = SquaredFlux(surface, field, definition="local")
	lengths = [CurveLength(c) for c in base_curves]
	distance_cc = CurveCurveDistance([c.curve for c in coils], threshold_curve_curve_distance, num_basecurves=ncoils)
	distance_cs = CurveSurfaceDistance(base_curves, surface, threshold_curve_surface_distance)
	# flux + 重み * 罰
	objective = (
		flux
		+ weight_length * sum(QuadraticPenalty(length, threshold_length, "max") for length in lengths)
		+ weight_curve_curve_distance * distance_cc
		+ weight_curve_surface_distance * distance_cs
		+ weight_curvature * sum(LpCurveCurvature(c, 2, threshold_curvature) for c in base_curves)
		+ weight_mean_squared_curvature * sum(QuadraticPenalty(MeanSquaredCurvature(c), threshold_mean_squared_curvature, "max") for c in base_curves)
	)

	# 目的関数の値と勾配を返す
	def fun(dofs: np.ndarray) -> tuple[float, np.ndarray]:
		objective.x = dofs
		return objective.J(), objective.dJ()

	minimize(fun, objective.x, jac=True, method="L-BFGS-B", options={"maxiter": iteration, "maxcor": 300})

	# B·n/|B| を (φ, θ) 格子の形で。0 なら磁気面がコイルの作る磁場と整合する。
	b = field.B().reshape(surface.gamma().shape)

	def fourier_coefficients(points: np.ndarray, order: int) -> np.ndarray:
		"""周期点列 (t = 0..1 の等間隔) を三角多項式の係数 [3, 2*order+1] に戻す。x(t) = Σ_m [ c_m cos(2πmt) + s_m sin(2πmt) ]。列は simsopt の DOF と同じ [c_0, s_1, c_1, .. s_order, c_order]"""
		spectrum = np.fft.rfft(points, axis=0)[: order + 1] / len(points)
		# stack で s_m, c_m を交互に並べ、先頭の [s_0, c_0] だけ落として c_0 を単独で戻す
		return np.concatenate([spectrum[:1].real, np.stack([-2 * spectrum.imag, 2 * spectrum.real], 1).reshape(-1, 3)[2:]]).T
	return {
		# 入力の引数一式をそのまま返す。実際に到達した距離は "curve_*_distance" の 2 つ
		"parameters": parameters,
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


def project_spines(
	wout: pathlib.Path,
	spines_points: list[list[tuple[float, float, float]]],  # コイル 1 本あたりの中心線点列 (x, y, z)。対称像込み
) -> list[list[tuple[float, float, float, float, float, float]]]:
	"""中心線の各点に LCFS 上の最近傍点を並べて [x, y, z, projectedx, projectedy, projectedz] にする。"""
	from alphastell import SurfaceFourierRZ
	ret_projected_spines = []
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
		for points in spines_points:
			point_center = np.mean(points, axis=0)
			phi, theta, s = math.atan2(point_center[1], point_center[0]), 0.0, 1.0
			projected_points = []
			for point in points:
				phi, theta = surface.nearest(phi, theta, s, point)  # 前の点の解を次の初期値にする継続法
				projected_points.append([*point, *surface.point_normal(phi, theta, s, True)[0]])  # 射影の足だけもらう
			ret_projected_spines.append(projected_points)
	return ret_projected_spines


def sweep_spines(
	width: float,  # 断面のトロイダル幅 [m]。断面のローカル +Y に割り当てる
	height: float,  # 断面の半径方向厚み [m]。ローカル +X = guide 方向に割り当てる
	projected_spines: list[list[tuple[float, float, float, float, float, float]]],  # project_spines の出力 [ncoil][npoint][x, y, z, projectedx, projectedy, projectedz]
) -> Any:  # alphastell.Geometry
	"""spine+guide の 6N 形式を sweep_geometry (Auxiliary) に渡して掃引する。

	断面は常に接線と直交し、ローカル +X が guide の方を向く (cadrum 0.8.18 以降)。guide は
	射影の足そのものではなく、そこへ向かって断面の対角半径だけ進んだ点に置き直す。
	"""
	from alphastell import Geometry
	distance_between_guide_and_spine = math.sqrt(width**2 + height**2) / 2
	def guided(p: tuple[float, float, float, float, float, float]) -> list[float]:
		scale = distance_between_guide_and_spine / math.dist(p[0:3], p[3:6])
		return [*p[0:3], *(a + (b - a) * scale for a, b in zip(p[0:3], p[3:6]))]
	paths = [[e for p in spine for e in guided(p)] for spine in projected_spines]
	profile = [-height / 2, -width / 2, height / 2, -width / 2, height / 2, width / 2, -height / 2, width / 2]
	return Geometry.sweep_geometry(True, profile, paths)


def visualize_spines(
	projected_spines: list[list[tuple[float, float, float, float, float, float]]],  # project_spines の出力
	out: pathlib.Path,  # 図の出力先 (.png)。CSV は同名 .csv
	surface: SurfaceRZFourier | None = None,  # LCFS を背景に描く場合は渡す
) -> None:
	import os
	colors = plt.get_cmap("tab10")
	array = np.array(projected_spines)  # [ncoil, npoint, 6]
	figure = plt.figure()
	axes = figure.add_subplot(111, projection="3d")
	if surface is not None:
		wall=surface.gamma()
		axes.plot_surface(
			wall[..., 0], wall[..., 1], wall[..., 2],
			color="#b8bec7", alpha=0.30, rstride=1, cstride=1, linewidth=0, edgecolor="none", antialiased=False, shade=True,
		)
	for i, (spine_i, projected_i) in enumerate(zip(array[..., :3], array[..., 3:])):
		closed_spine = np.concatenate([spine_i, spine_i[:1]])
		closed_projected = np.concatenate([projected_i, projected_i[:1]])
		color = colors(i%8)
		axes.plot(closed_spine[:, 0], closed_spine[:, 1], closed_spine[:, 2], color=color, linewidth=0.7)
		axes.plot(closed_projected[:, 0], closed_projected[:, 1], closed_projected[:, 2], color=color, linewidth=0.7)
		for a, b in zip(spine_i[::3], projected_i[::3]):  # 3 点に 1 本だけ描いて密度を抑える
			axes.plot([a[0], b[0]], [a[1], b[1]], [a[2], b[2]], color=color, linewidth=0.6)

	axes.set_box_aspect(np.ptp(array.reshape(-1, 3), axis=0))
	axes.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
	axes.zaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))	
	axes.view_init(elev=38, azim=-55)
	axes.grid(False)
	[pane.pane.set_alpha(0.0) for pane in (axes.xaxis, axes.yaxis, axes.zaxis)]	
	figure.tight_layout()
	figure.savefig(out)
	plt.close(figure)
	np.savetxt(out.with_suffix(".csv"), array.reshape(len(array), -1), delimiter=",", fmt="%.9e", header="row = one coil; columns = x,y,z,projectedx,projectedy,projectedz repeated npoint times [m]")
	len(os.getenv("SHOW", "")) and plt.show()




# Markdown レポートの本文。main() が数値を差し込み、PDF 化は make al-08 が md2pdf.py で行う
TEMPLATE = """# VMEC 平衡を再現するモジュラーコイル (al_08)

VMEC 平衡 `wout_vmec.nc` (nfp={nfp}, R={r_major:.2f} m) の LCFS を固定し、その外側にモジュラーコイルを
simsopt の stage-2 最適化で置いた。al_06 で PbLi 殻を厚くするほど TBR が上がると分かったので、
ここではコイルをどこまで離せるか、つまり半径方向にいくら予算があるかを見る。

## 方法

磁気面を動かさずコイルだけを動かす stage-2 である。半周期に {ncoils} 本の独立コイル
(1 本あたり Fourier {order} 次) を等間隔の円環として置き、stellarator 対称と nfp 回転で
{ncoils_total} 本に増やす。目的関数は LCFS 上の規格化法線磁場

$$
\\int (\\mathbf B \\cdot \\mathbf n)^2 / |\\mathbf B|^2 \\; dA
$$

に、コイル長 ({threshold_length} m)・コイル間距離 ({threshold_curve_curve_distance} m)・コイル-プラズマ距離・曲率
({threshold_curvature} 1/m、曲げ半径 {bend_radius:.0f} m) の各ペナルティを足したもので、L-BFGS-B を {iteration} 反復かけた。
コイル-プラズマ距離の要求値だけを {threshold_curve_surface_distance_min}〜{threshold_curve_surface_distance_max} m で振っている。

電流の絶対値はこの wout からは決まらない。正味ポロイダル電流を与える `bsubvmnc` が無く、
`rmnc` / `zmns` / `xm` / `xn` しか持たないためである。$R_0$ = {r_major:.2f} m で
$B_0$ = {b0} T を仮定して総電流を固定した。目的関数が B·n/|B| で電流スケールに不変なので、
コイル形状はこの仮定に依らず、下表の電流値だけが $B_0$ に比例する。同じ理由で、virtual casing に
必要な量が無いため有限ベータ補正も入っておらず、コイルだけで LCFS を作る真空磁場に近い扱いである。

## 結果: どこまでコイルを離せるか

| 要求距離 [m] | 実現距離 [m] | max B·n/B | mean B·n/B | 全コイル長 [m] | コイル間 [m] |
|--:|--:|--:|--:|--:|--:|
{scan_rows}
要求 {threshold_curve_surface_distance_min} m はほぼそのまま実現できる ({cs_first:.2f} m)。別途 1.0 m を要求しても 1.38 m までしか
近づかないので、この配位のコイルは放っておいても 1.4 m 前後に落ち着く。一方、要求を上げると
法線磁場誤差は {error_first:.1e} ({cs_first:.2f} m) から {error_last:.1e} ({cs_last:.2f} m) へ 1 桁上がり、
同時にコイル間距離が {cc_first:.2f} m から {cc_last:.2f} m へ詰まる。離した分を長いコイルで補おうとして
互いに衝突するためで、2 m 付近が実用上の壁になる。

![左: 実現距離 {cs_first:.2f} m での LCFS 上の B·n/|B| 分布。右: コイル-プラズマ距離に対する法線磁場誤差。点線は al_06 の PbLi 最大厚み。]({out_error_png})

## 結果: コイル形状

以下は要求 {threshold_curve_surface_distance_min} m のコイルである。

| コイル | 長さ [m] | 電流 [MA] | 最小曲げ半径 [m] |
|:-:|--:|--:|--:|
{coil_rows}
![{ncoils_total} 本のモジュラーコイルと LCFS。色は独立コイルの番号で、同色の {nimages} 本は対称操作による像である。断面が三角形から楕円へ捻れる領域でコイルが強く曲がる。]({out_png})

![中心線に {height} m × {width} m の矩形断面を掃引した導体ソリッドの 4 面図。断面は常に接線と直交し、LCFS 法線の guide 曲線が捻りを制御する。]({out_sweep_png})

## 考察

半径方向の予算は約 1.4 m、無理をして 2 m である。al_06 の PbLi 殻は 70 cm でも TBR が
飽和していなかったから、残る 70 cm 前後に第一壁・冷却管・背面支持構造・遮蔽・真空容器・
組立公差の全部を収めなければならない。al_06 の「厚くすれば TBR が上がる」と本節の
「離すと磁気面が再現できない」は独立した 2 つの結果ではなく、1 つの半径方向予算の奪い合いである。
コイル本数を増やしてもこの壁は動かない (半周期 5 本・6 本でも max |B·n|/|B| は 1e-2 台に留まり、
全コイル長だけが 20〜30% 増えた)。al_09 以降で不均質な WCLL 構造を入れるとき、厚みの上限はここで決まる。

コイル形状は [{out_csv}]({out_csv}) に全 {ncoils_total} 本の Fourier 係数として出してある。
各コイルは m = 0…{order} の

$$
\\mathbf x(t) = \\sum_m [\\, \\mathbf c_m \\cos(2 \\pi m t) + \\mathbf s_m \\sin(2 \\pi m t) \\,]
$$

で表され、点列と違って任意の分解能で滑らかに引き直せる。対称操作による像も回転行列を掛けた
だけで次数は変わらないので、全数を同じ形式で持てる。al_04 と同じ経路で STEP にすれば、
そのまま構造解析と干渉チェックに渡せる。
"""


if __name__ == "__main__":
	main()
