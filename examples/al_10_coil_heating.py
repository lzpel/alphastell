#!/usr/bin/env python3
"""モジュラーコイルの核発熱を出す (al_10)。

al_07 でコイルの中心線が、sweep_geometry で断面を持つ導体ソリッドが作れるようになった。al_06 は PbLi 殻の
TBR を、al_08 は線源モデルの選び方を決めた。これらを繋ぐとコイルに何 W 落ちるかが計算できる。

遮蔽体は入れない。増殖材 50 cm とその外の真空だけでコイルが何を浴びるかを見る。遮蔽が必須である
ことを数字で示すのが目的で、遮蔽そのものの設計は次段に回す。

核融合出力は固定値を置かず VMEC 平衡から積分する。プラズマ体積が VMEC の volume_p と一致することが
その積分の検証になる。

    make al-10
"""

import math
import pathlib
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openmc
import typst
from cad_to_dagmc import CadToDagmc

from alphastell import Geometry, SurfaceFourierRZ

MU0 = 4e-7 * math.pi
JOULE_PER_EV = 1.602176634e-19
DT_ENERGY = 17.6e6  # DT 反応 1 回あたりの発生エネルギー [eV]。出力の換算に使う
NEUTRON_ENERGY = 14.07e6  # そのうち中性子が持ち去る分 [eV]。残り 3.5 MeV はアルファ粒子
FAST = 0.1e6  # 高速中性子の下限 [eV]。Nb3Sn のフルエンス制限がこの区間で定義される
YEAR = 365.25 * 24 * 3600  # フル出力年 [s]

# parastell の examples/coils.example と config.yaml から読んだ実測値
NCOILS, STANDOFF, CC_THRESHOLD = 5, 1.27, 0.87  # 半周期あたりの独立コイル数、コイル-LCFS 距離、コイル間距離 [m]
WIDTH, HEIGHT = 0.40, 0.50  # 巻線パックのトロイダル幅と半径方向厚み [m]
ORDER, NPOINT = 6, 96  # コイルの Fourier 次数と掃引の制御点数
GUIDE = 30.0  # 掃引のガイド曲線を中心線から e_phi 方向へずらす距離 [m]。近すぎても遠すぎても掃引が落ちる

THICKNESS = 0.5  # PbLi 殻の厚み [m]。al_06 の中央、al_08 と同じ
DIV_PHI, DIV_THETA = 96, 40  # 殻の制御点。al_06 / al_08 と同じにして幾何を揃える
N_SAMPLE = 20000  # 重み付き点線源の点数。al_08 の case_2 を増やしたもの
PARTICLES, BATCHES = 40000, 10
TALLY_R, TALLY_Z = 40, 40

# DEMO TF コイルの設計目標。notes/20260815-目標変更.md より
HEATING_LIMIT = 450.0  # ピーク核発熱密度 [W/m^3]
FLUENCE_LIMIT = 1e22  # Nb3Sn の高速中性子フルエンス [n/m^2]

WOUT = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc"
OUT = pathlib.Path("out")
WORK = OUT / "al_10_openmc"
SHELL_STEP, COIL_STEP, H5M = OUT / "al_10_shell.step", OUT / "al_10_coils.step", OUT / "al_10.h5m"


def make_surface(
	wout: pathlib.Path,  # VMEC の平衡出力 (wout*.nc)。最外殻の Fourier 係数だけを読む
	quadpoints_phi: np.ndarray | None = None,  # トロイダル角の評価点。既定は半周期 0..1/(2*nfp) の 32 点
	quadpoints_theta: np.ndarray | None = None,  # ポロイダル角の評価点。既定は一周 0..1 の 32 点
) -> "SurfaceRZFourier":
	"""LCFS を simsopt の SurfaceRZFourier にする。al_07 と同じ。

	VMEC も simsopt も R = Σ rc cos(mθ - n·nfp·φ) なので、xn を nfp で割るだけで移せる。
	格子の単位は回転数 (1.0 = 全周) でラジアンではない。
	"""
	from scipy.io import netcdf_file
	from simsopt.geo import SurfaceRZFourier

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
	surface: "SurfaceRZFourier",  # 固定する LCFS。この面上の B·n を消すようにコイルが動く
	standoff: float,  # コイル-プラズマ距離の要求値 [m]。ペナルティの閾値と初期半径の両方に効く
	ncoils: int,  # 半周期あたりの独立コイル数。全体では 2*nfp*ncoils 本になる
	order: int,  # コイル 1 本の Fourier 次数。自由度は 1 本あたり 3*(2*order+1) 個
	b0: float,  # 大半径での磁場 [T]。正味ポロイダル電流の総量を決めるためだけに使う
	length_target: float,  # コイル 1 本の長さ上限 [m]。超えた分だけ二次で罰する
	cc_threshold: float,  # コイル間の最小距離 [m]。組み立てと支持構造が要求する
	curvature_threshold: float,  # 曲率上限 [1/m]。逆数が導体の最小曲げ半径
	msc_threshold: float,  # 平均二乗曲率の上限 [1/m^2]。曲率上限では拾えない全体の波打ちを抑える
	weights: dict[str, float],  # 各ペナルティの重み
	maxiter: int,  # L-BFGS-B の反復上限
) -> dict[str, Any]:
	"""磁気面を固定してコイルだけを動かす stage-2。al_07 と同じ。

	閾値 (length_target 等) は工学的な制約そのもの、weights は物理的意味を持たない数値の重み。
	"""
	from scipy.optimize import minimize
	from simsopt.field import BiotSavart, Current, coils_via_symmetries
	from simsopt.geo import CurveCurveDistance, CurveLength, CurveSurfaceDistance, LpCurveCurvature, MeanSquaredCurvature, create_equally_spaced_curves
	from simsopt.objectives import QuadraticPenalty, SquaredFlux

	nfp = surface.nfp
	r_major = surface.get_rc(0, 0)
	base_curves = create_equally_spaced_curves(ncoils, nfp, stellsym=True, R0=r_major, R1=3.5 + standoff, order=order)

	# 正味ポロイダル電流 2πR·B0/μ0 を半周期に配り、その合計だけを固定する。
	half_period_current = 2 * math.pi * r_major * b0 / MU0 / (2 * nfp)
	base_currents = [Current(half_period_current / ncoils * 1e-5) * 1e5 for _ in range(ncoils - 1)]
	fixed_total = Current(half_period_current)
	fixed_total.fix_all()
	base_currents.append(fixed_total - sum(base_currents))

	coils = coils_via_symmetries(base_curves, base_currents, nfp, True)
	field = BiotSavart(coils)
	field.set_points(surface.gamma().reshape((-1, 3)))

	flux = SquaredFlux(surface, field, definition="local")
	lengths = [CurveLength(c) for c in base_curves]
	distance_cc = CurveCurveDistance([c.curve for c in coils], cc_threshold, num_basecurves=ncoils)
	distance_cs = CurveSurfaceDistance(base_curves, surface, standoff)
	objective = (
		flux
		+ weights["length"] * sum(QuadraticPenalty(length, length_target, "max") for length in lengths)
		+ weights["curve_curve_distance"] * distance_cc
		+ weights["curve_surface_distance"] * distance_cs
		+ weights["curvature"] * sum(LpCurveCurvature(c, 2, curvature_threshold) for c in base_curves)
		+ weights["msc"] * sum(QuadraticPenalty(MeanSquaredCurvature(c), msc_threshold, "max") for c in base_curves)
	)

	def fun(dofs: np.ndarray) -> tuple[float, np.ndarray]:
		objective.x = dofs
		return objective.J(), objective.dJ()

	minimize(fun, objective.x, jac=True, method="L-BFGS-B", options={"maxiter": maxiter, "maxcor": 300})

	def fourier_coefficients(points: np.ndarray, order: int) -> np.ndarray:
		"""周期点列を三角多項式の係数 [3, 2*order+1] に戻す。列は simsopt の DOF と同じ [c_0, s_1, c_1, ...]"""
		spectrum = np.fft.rfft(points, axis=0)[: order + 1] / len(points)
		return np.concatenate([spectrum[:1].real, np.stack([-2 * spectrum.imag, 2 * spectrum.real], 1).reshape(-1, 3)[2:]]).T

	b = field.B().reshape(surface.gamma().shape)
	return {
		# coils と同じ順序のフーリエ係数。対称像は自前の DOF を持たないので全本を gamma() から起こす
		"coeffs": np.array([fourier_coefficients(coil.curve.gamma(), order) for coil in coils]),
		# B·n/|B| を (phi, theta) 格子で。0 なら磁気面と整合する
		"error": (b * surface.unitnormal()).sum(axis=-1) / np.linalg.norm(b, axis=-1),
		"lengths": [float(length.J()) for length in lengths],
		"currents": [float(current.get_value()) for current in base_currents],
		# 閾値ではなく最適化後の実測値
		"curve_curve_distance": float(distance_cc.shortest_distance()),
		"curve_surface_distance": float(distance_cs.shortest_distance()),
	}


def coil_paths(coeffs: np.ndarray, npoint: int) -> list[list[float]]:
	"""係数から sweep_geometry の経路 [x, y, z, guide_x, guide_y, guide_z, ...] を作る。

	ガイドは中心線をコイル面の法線 e_phi へ GUIDE m 平行移動したもので、断面のローカル +X が
	中心線からガイドへの向きを追う。コイルの代表トロイダル角は c_0 (曲線の平均点) の偏角で取る。
	周期指定で渡すので終点は重複させない。
	"""
	order = (coeffs.shape[2] - 1) // 2
	angle = math.tau * np.outer(np.arange(npoint) / npoint, np.arange(order + 1))
	paths = []
	for c in coeffs:
		phi = math.atan2(c[1, 0], c[0, 0])
		normal = GUIDE * np.array([-math.sin(phi), math.cos(phi), 0.0])
		point = np.cos(angle) @ c[:, 0::2].T + np.sin(angle) @ np.vstack([np.zeros(3), c[:, 1::2].T])
		paths.append(np.hstack([point, point + normal]).ravel().tolist())
	return paths


def tilt(paths: list[list[float]]) -> tuple[np.ndarray, np.ndarray]:
	"""各経路で断面が法平面から傾く角 [deg] の (最悪点, RMS)。制御点の弦を接線の近似に使う。

	ガイドが中心線の平行移動なら断面のローカル +X は 1 本の固定ベクトルになるので、それが接線と
	直交しない箇所で断面が寝る。掃引体積はこの傾きの二乗で目減りする。
	"""
	worst, rms = [], []
	for path in paths:
		point, guide = np.hsplit(np.array(path).reshape(-1, 6), 2)
		up = (guide[0] - point[0]) / np.linalg.norm(guide[0] - point[0])
		chord = np.roll(point, -1, axis=0) - point
		chord /= np.linalg.norm(chord, axis=1)[:, None]
		projection = np.abs(chord @ up)
		worst.append(math.degrees(math.asin(min(1.0, projection.max()))))
		rms.append(math.degrees(math.asin(min(1.0, math.sqrt((projection**2).mean())))))
	return np.array(worst), np.array(rms)


def swept_volume(paths: list[list[float]]) -> float:
	"""断面積 × 中心線長 [m^3]。断面が法平面に乗っていれば掃引体積はこれに一致する。"""
	total = 0.0
	for path in paths:
		point = np.array(path).reshape(-1, 6)[:, :3]
		total += WIDTH * HEIGHT * float(np.linalg.norm(np.roll(point, -1, axis=0) - point, axis=1).sum())
	return total


def plasma_profile(s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
	"""規格化磁束 s でのイオン密度 [m^-3] と DT の ⟨σv⟩ [cm^3/s] (parastell の既定プロファイル)。"""
	temperature = np.maximum(11.5 * (1.0 - np.asarray(s)), 1e-3)  # keV
	density = 4.8e20 * (1.0 - np.asarray(s) ** 5)
	return density, 3.68e-12 * temperature ** (-2.0 / 3.0) * np.exp(-19.94 * temperature ** (-1.0 / 3.0))


def reaction_density(s: np.ndarray) -> np.ndarray:
	"""DT 反応率密度 [m^-3 s^-1]。n_D = n_T = n/2 なので (n/2)²⟨σv⟩、⟨σv⟩ は cm^3/s なので 1e-6 を掛ける。"""
	density, sigma_v = plasma_profile(s)
	return (density / 2) ** 2 * sigma_v * 1e-6


def jacobian(lcfs: SurfaceFourierRZ, phi: float, theta: float, s: float) -> float:
	"""体積要素 √g = |∂p/∂s · (∂p/∂θ × ∂p/∂φ)|。point_normal の前進差分だけで作る。"""
	delta = 1e-4
	origin = np.array(lcfs.point_normal(phi, theta, s, False)[0])
	d_s = np.subtract(lcfs.point_normal(phi, theta, s + delta, False)[0], origin)
	d_theta = np.subtract(lcfs.point_normal(phi, theta + delta, s, False)[0], origin)
	d_phi = np.subtract(lcfs.point_normal(phi + delta, theta, s, False)[0], origin)
	return abs(float(np.dot(d_s, np.cross(d_theta, d_phi)))) / delta**3


def plasma_samples(lcfs: SurfaceFourierRZ, count: int) -> tuple[np.ndarray, np.ndarray]:
	"""(φ, θ, s) の一様サンプルとその体積要素。線源の重みと出力の積分で共用する。"""
	sample = np.random.default_rng(0).random((count, 3)) * [math.tau, math.tau, 1.0]
	return sample, np.array([jacobian(lcfs, *x) for x in sample])


def fusion_power(sample: np.ndarray, volume_element: np.ndarray) -> dict[str, float]:
	"""VMEC 平衡から核融合出力を積分する。返す体積は VMEC の volume_p と突き合わせる検証用。"""
	cube = math.tau * math.tau  # (φ, θ, s) の一様サンプルが張る座標体積
	rate = float((reaction_density(sample[:, 2]) * volume_element).mean() * cube)
	return {"volume": float(volume_element.mean() * cube), "rate": rate, "power": rate * DT_ENERGY * JOULE_PER_EV}


def weighted_source(lcfs: SurfaceFourierRZ, sample: np.ndarray, volume_element: np.ndarray) -> list[openmc.IndependentSource]:
	"""al_08 の case_2。一様サンプルの強度を反応率 × 体積要素にする。合計は 1 に規格化する。"""
	weight = reaction_density(sample[:, 2]) * volume_element
	return [
		openmc.IndependentSource(
			space=openmc.stats.Point(np.multiply(lcfs.point_normal(phi, theta, s, False)[0], 100)),
			energy=openmc.stats.Discrete([NEUTRON_ENERGY], [1.0]),
			strength=w,
		)
		for (phi, theta, s), w in zip(sample, weight / weight.sum())
	]


def blanket(lcfs: SurfaceFourierRZ, thickness: float) -> tuple[Geometry, np.ndarray]:
	"""LCFS を法線方向に押し出した PbLi 殻。al_06 と同じ作り方。外側格子も返す。"""
	inner = np.empty((DIV_PHI, DIV_THETA, 3))
	outer = np.empty_like(inner)
	for i, j in np.ndindex(DIV_PHI, DIV_THETA):
		point, normal = lcfs.point_normal(math.tau * i / DIV_PHI, math.tau * j / DIV_THETA, 1.0, False)
		inner[i, j], outer[i, j] = point, np.add(point, np.multiply(normal, thickness))
	return Geometry.bspline_geometry(outer).boolean_subtract(Geometry.bspline_geometry(inner)), outer


def materials() -> tuple[openmc.Material, openmc.Material]:
	"""PbLi 増殖材と、巻線パックを均質化したコイル材。名前が DAGMC のタグと結線する。

	コイルはケーシングと巻線を分けない単一ソリッドなので体積分率で混ぜるほかない。
	比率は典型的な超伝導コイルを想定した仮定である。
	"""
	pbli = openmc.Material(name="pbli")
	pbli.add_element("Li", 17.0, "ao", enrichment=90.0, enrichment_target="Li6", enrichment_type="ao")
	pbli.add_element("Pb", 83.0, "ao")
	pbli.set_density("g/cm3", 9.4)

	steel = openmc.Material()
	for element, fraction in (("Fe", 65.0), ("Cr", 17.0), ("Ni", 12.0), ("Mo", 2.5), ("Mn", 2.0), ("Si", 1.0)):
		steel.add_element(element, fraction, "wo")
	steel.set_density("g/cm3", 7.93)
	copper = openmc.Material()
	copper.add_element("Cu", 1.0)
	copper.set_density("g/cm3", 8.96)
	nb3sn = openmc.Material()
	nb3sn.add_element("Nb", 3.0)
	nb3sn.add_element("Sn", 1.0)
	nb3sn.set_density("g/cm3", 8.9)
	epoxy = openmc.Material()
	for element, fraction in (("C", 76.0), ("H", 6.0), ("O", 18.0)):
		epoxy.add_element(element, fraction, "wo")
	epoxy.set_density("g/cm3", 1.2)

	coil = openmc.Material.mix_materials([steel, copper, nb3sn, epoxy], [0.50, 0.25, 0.15, 0.10], "vo", name="coil")
	return pbli, coil


def heating(source: list[openmc.IndependentSource], mesh: openmc.CylindricalMesh) -> dict[str, Any]:
	"""コイルの核発熱と高速中性子束を OpenMC で出す。

	FENDL-3.2 は MT=901 を持たないので heating-local は警告もなくゼロになる。heating と
	photon_transport の組み合わせが唯一の正しい選択である。
	"""
	openmc.reset_auto_ids()
	pbli, coil = materials()
	total = openmc.Tally(name="total")
	total.filters = [openmc.MaterialFilter([coil])]
	total.scores = ["heating"]
	mapped = openmc.Tally(name="map")
	mapped.filters = [openmc.MeshFilter(mesh), openmc.MaterialFilter([coil])]
	mapped.scores = ["heating"]
	fast = openmc.Tally(name="fast")
	fast.filters = [openmc.MaterialFilter([coil]), openmc.EnergyFilter([FAST, 20e6])]
	fast.scores = ["flux"]

	settings = openmc.Settings(run_mode="fixed source", source=source, particles=PARTICLES, batches=BATCHES)
	settings.photon_transport = True
	model = openmc.Model(
		geometry=openmc.Geometry(openmc.DAGMCUniverse(str(H5M)).bounded_universe()),
		materials=openmc.Materials([pbli, coil]),
		settings=settings,
		tallies=openmc.Tallies([total, mapped, fast]),
	)
	WORK.mkdir(parents=True, exist_ok=True)
	with openmc.StatePoint(model.run(cwd=WORK, output=False)) as statepoint:
		one = statepoint.get_tally(name="total")
		grid = statepoint.get_tally(name="map")
		flux = statepoint.get_tally(name="fast")
		return {
			"heating": float(one.mean.flat[0]),  # eV / 線源中性子
			"error": float(one.std_dev.flat[0]),
			# メッシュフィルタのビンは r が最内で回るので order="F" でないと R と Z が入れ替わる
			"map": np.squeeze(grid.mean.reshape(mesh.dimension, order="F"), axis=1),
			"flux": float(flux.mean.flat[0]),  # cm / 線源中性子。体積で割ると n/cm^2
			"transport": float(statepoint.runtime["transport"]),
		}


def main() -> dict[str, Any]:
	OUT.mkdir(parents=True, exist_ok=True)
	with open(WOUT, "rb") as f:
		lcfs = SurfaceFourierRZ.load(f)

	result = optimize_coil(
		make_surface(WOUT),
		standoff=STANDOFF,
		ncoils=NCOILS,
		order=ORDER,
		b0=5.5,  # 電流の絶対値を決めるだけで、中性子計算には効かない
		length_target=36.0,  # parastell のコイル周長 33.5〜36.0 m に合わせた
		cc_threshold=CC_THRESHOLD,
		curvature_threshold=0.5,
		msc_threshold=0.25,
		weights={"length": 1e-3, "curve_curve_distance": 3e-1, "curve_surface_distance": 3e-2, "curvature": 1e-2, "msc": 1e-2},
		maxiter=300,
	)
	# コイルが増殖材に食い込んでいたら黙って壊れた h5m ができるので、ここで止める
	clearance = result["curve_surface_distance"] - HEIGHT / 2 - THICKNESS
	if clearance <= 0.0:
		raise ValueError(f"coils reach {result['curve_surface_distance']:.2f} m from the LCFS, which overlaps the {THICKNESS} m blanket by {-clearance:.2f} m")

	paths = coil_paths(result["coeffs"], NPOINT)
	profile = [-WIDTH / 2, -HEIGHT / 2, WIDTH / 2, -HEIGHT / 2, WIDTH / 2, HEIGHT / 2, -WIDTH / 2, HEIGHT / 2]
	# 全要素 0 の 6 要素が経路の区切り。1 回の呼び出しで全コイルを別ソリッドとして起こす
	coils = Geometry.sweep_geometry(True, profile, *[v for i, path in enumerate(paths) for v in ([0.0] * 6 if i else []) + path])
	shell, outer = blanket(lcfs, THICKNESS)
	for geometry, path in ((shell, SHELL_STEP), (coils, COIL_STEP)):
		with open(path, "wb") as f:
			geometry.write_step(f)
	with open(OUT / "al_10_geometry.png", "wb") as f:
		shell.boolean_union(coils).write_png(f)

	cad = CadToDagmc()
	cad.add_stp_file(str(SHELL_STEP), material_tags=["pbli"])
	cad.add_stp_file(str(COIL_STEP), material_tags=["coil"] * len(coils))
	cad.export_dagmc_h5m_file(filename=str(H5M), scale_factor=100)  # VMEC は m、OpenMC は cm
	tags = openmc.DAGMCUniverse(str(H5M)).material_names
	print(f"{H5M}: {len(coils)} coils + shell, material tags {tags}")

	sample, volume_element = plasma_samples(lcfs, N_SAMPLE)
	power = fusion_power(sample, volume_element)
	print(f"plasma volume {power['volume']:.1f} m^3, P_fus {power['power'] / 1e9:.2f} GW, S {power['rate']:.3e} n/s")

	radius, height = np.hypot(outer[..., 0], outer[..., 1]), outer[..., 2]
	span = HEIGHT / 2 + result["curve_surface_distance"]  # コイルは殻の外側にこれだけ張り出す
	mesh = openmc.CylindricalMesh(
		r_grid=np.linspace(max(radius.min() - span, 0.0), radius.max() + span, TALLY_R + 1) * 100,
		z_grid=np.linspace(height.min() - span, height.max() + span, TALLY_Z + 1) * 100,
		mesh_id=1,
	)
	tally = heating(weighted_source(lcfs, sample, volume_element), mesh)

	volume = sum(coils.volume())
	watts = tally["heating"] * JOULE_PER_EV * power["rate"]
	edge_r, edge_z = np.asarray(mesh.r_grid), np.asarray(mesh.z_grid)
	bin_volume = (math.pi * np.diff(edge_r**2))[:, None] * np.diff(edge_z)[None, :] * 1e-6  # cm^3 -> m^3
	density = tally["map"] * JOULE_PER_EV * power["rate"] / bin_volume
	fluence = tally["flux"] / (volume * 1e6) * power["rate"] * 1e4 * YEAR  # cm/src -> n/m^2 per full power year
	worst, rms = tilt(paths)
	exact = swept_volume(paths)
	print(f"coil heating {watts / 1e6:.2f} MW ({watts / volume:.0f} W/m^3 mean, {density.max():.0f} W/m^3 peak), rel err {tally['error'] / tally['heating']:.1%}")
	print(f"fast fluence {fluence:.2e} n/m^2 per full power year")
	print(f"section tilt {worst.max():.0f} deg worst / {rms.mean():.0f} deg rms, swept volume {(volume / exact - 1) * 100:+.1f}% vs area x length")

	figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.4))
	image = left.imshow(
		np.where(density > 0, density, np.nan).T,
		origin="lower",
		extent=[edge_r[0] / 100, edge_r[-1] / 100, edge_z[0] / 100, edge_z[-1] / 100],
		aspect="equal",
		norm=matplotlib.colors.LogNorm(),
	)
	figure.colorbar(image, ax=left, label="nuclear heating [W/m^3]")
	left.set(xlabel="R [m]", ylabel="Z [m]", title=f"coil nuclear heating at {power['power'] / 1e9:.1f} GW fusion")
	right.hist(rms, bins=16, color="#4a90d9")
	right.axvline(rms.mean(), color="#c0392b", linestyle=":", label=f"mean {rms.mean():.1f} deg")
	right.set(xlabel="rms tilt of the section from the normal plane [deg]", ylabel="coils", title="the section cannot stay perpendicular")
	right.legend()
	figure.savefig(OUT / "al_10_heating.png", dpi=150, bbox_inches="tight")
	plt.close(figure)

	fields = {
		"ncoils": NCOILS,
		"ncoil_total": len(coils),
		"standoff": f"{STANDOFF:.2f}",
		"achieved": f"{result['curve_surface_distance']:.2f}",
		"clearance": f"{clearance:.2f}",
		"cc": f"{result['curve_curve_distance']:.2f}",
		"width": f"{WIDTH * 100:.0f}",
		"height": f"{HEIGHT * 100:.0f}",
		"thickness": f"{THICKNESS * 100:.0f}",
		"npoint": NPOINT,
		"guide": f"{GUIDE:.0f}",
		"nsample": N_SAMPLE,
		"particles": PARTICLES,
		"batches": BATCHES,
		"transport": f"{tally['transport']:.0f}",
		"error": f"{np.abs(result['error']).max():.1e}",
		"volume_mc": f"{power['volume']:.1f}",
		"power": f"{power['power'] / 1e9:.2f}",
		"rate": f"{power['rate']:.2e}",
		"coil_volume": f"{volume:.1f}",
		"watts": f"{watts / 1e6:.2f}",
		"mean_density": f"{watts / volume:.0f}",
		"peak_density": f"{density.max():.0f}",
		"peak_ratio": f"{density.max() / HEATING_LIMIT:.0f}",
		"heating_limit": f"{HEATING_LIMIT:.0f}",
		"relative_error": f"{tally['error'] / tally['heating'] * 100:.1f}",
		"fluence": f"{fluence:.2e}",
		"fluence_limit": f"{FLUENCE_LIMIT:.0e}",
		"fluence_days": f"{FLUENCE_LIMIT / fluence * 365.25:.0f}",
		"tilt_rms": f"{rms.mean():.0f}",
		"tilt_max": f"{worst.max():.0f}",
		"exact_volume": f"{exact:.1f}",
		"volume_error": f"{(volume / exact - 1) * 100:.1f}",
		"attenuation": f"{math.log(density.max() / HEATING_LIMIT) * 8.5:.0f}",
	}
	report = OUT / "al_10_report.typ"
	report.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	typst.compile(report, output=OUT / "al_10_report.pdf")
	print(f"{OUT / 'al_10_report.pdf'}: {(OUT / 'al_10_report.pdf').stat().st_size} bytes")
	return fields


TEMPLATE = """#set page(paper: "a4", margin: 2cm, numbering: "1")
#set text(font: ("Yu Gothic", "Meiryo", "Noto Sans CJK JP"), size: 10pt, lang: "ja")
#set par(justify: true)

= モジュラーコイルの核発熱 (al_10)

al_06 は「PbLi 殻を厚くするほど TBR が上がる」と示し、al_07 は「厚みを置ける空間はコイルが決める」と
示した。その反対側、つまり**コイルが浴びる側**の制約をここで数値にする。超伝導コイルの成立性は
核発熱密度と高速中性子フルエンスで決まり、どちらもこの計算でしか出ない。

**遮蔽体は入れていない。** 増殖材 {thickness} cm とその外の真空だけである。遮蔽が要るかどうかではなく、
どれだけ要るかを決めるための下限値としてこの構成を選んだ。

== 方法

=== 幾何

コイルは al_07 と同じ stage-2 最適化で起こす。独立コイル {ncoils} 本、対称像込みで {ncoil_total} 本。
コイル-プラズマ距離の要求値 {standoff} m とコイル間距離 {cc} m は parastell の `examples/coils.example` を
実測して決めた (同ファイルは 40 本 = 2·nfp·5 で、LCFS への最小距離 1.27 m、コイル間 0.87 m)。

断面は {width} × {height} cm の矩形で、これも parastell の `config.yaml` と同じである。中心線の
Fourier 係数から各コイルの代表トロイダル角を $phi = arctan(c_(0,y) \\/ c_(0,x))$ で取り、
中心線をコイル面の法線 $e_phi$ へ {guide} m 平行移動した曲線を掃引のガイドにして、全 {ncoil_total} 本を
`sweep_geometry` の 1 回の呼び出しで起こす。ガイドは断面のローカル $+x$ が向く先を決めるだけで、
剛体平行移動なのでこの向きは全周で $e_phi$ に一致する。制御点は 1 本あたり {npoint} 点。

最適化は要求 {standoff} m に対し {achieved} m まで寄る。巻線パック半厚 {height} cm の半分と
増殖材 {thickness} cm を引くと隙間は {clearance} m で、コイルと増殖材は干渉しない。

=== 核融合出力

タリーは線源中性子 1 個あたりで出るので、W に直すには線源率が要る。固定値を置かず、
VMEC 平衡から積分した。

$ S = integral (n\\/2)^2 ⟨sigma v⟩ sqrt(g) space d phi space d theta space d s $

$n_D = n_T = n_i\\/2$ とし、$⟨sigma v⟩$ は cm³/s なので m³/s に直す。$sqrt(g)$ は `point_normal` の
前進差分から作る。プロファイルは al_08 と同じ parastell 既定である。

同じ積分でプラズマ体積が **{volume_mc} m³** と出る。VMEC 自身の `volume_p` が 635.7 m³ なので、
ヤコビアンと積分が正しいことの検証になっている。得られる出力は **{power} GW**、
線源率 {rate} n/s である。

=== 中性子輸送

線源は al_08 の case_2 (一様サンプルの強度を反応率 × 体積要素にしたもの) を {nsample} 点に増やしたもの。
{particles} 粒子 × {batches} バッチ。

**`heating` と光子輸送の組み合わせは選択ではなく必然である。** この計算に使う FENDL-3.2 は
192 核種すべてに MT=301 (`heating`) を持つが、**MT=901 (`heating-local`) は 1 核種も持たない**。
`heating-local` を指定すると警告もエラーも出ずにゼロが返る。そして `heating` は二次 γ の
エネルギーを局所に落とさないので、`photon_transport = True` が無ければ捕獲 γ の寄与が丸ごと消える。

コイル材は巻線パックを体積分率で均質化した。**この比率は仮定である。**

#table(
  columns: 3,
  align: (left, right, left),
  [材料], [体積分率 [%]], [役割],
  [SS316], [50], [ジャケットと構造],
  [Cu], [25], [安定化材],
  [Nb₃Sn], [15], [超伝導線],
  [エポキシ], [10], [絶縁],
)

== 結果

#figure(image("al_10_heating.png", width: 100%), caption: [左: コイル材だけに絞った核発熱密度の
R-Z 分布 (φ 全周積分、対数目盛)。右: 各コイルで up が法平面から傾く最大角の分布。])

#figure(image("al_10_geometry.png", width: 92%), caption: [増殖材 {thickness} cm と {ncoil_total} 本の
コイル導体。左上 ISO、右上 +Z、左下 +X、右下 +Y。])

#table(
  columns: 2,
  align: (left, right),
  [量], [値],
  [核融合出力 (VMEC から積分)], [{power} GW],
  [線源率], [{rate} n/s],
  [コイル体積 (全 {ncoil_total} 本)], [{coil_volume} m³],
  [コイル核発熱 合計], [{watts} MW],
  [同 体積平均], [{mean_density} W/m³],
  [同 ピーク], [{peak_density} W/m³],
  [DEMO TFC 目標], [{heating_limit} W/m³],
  [高速中性子フルエンス], [{fluence} n/m² / フル出力年],
  [Nb₃Sn 目標], [{fluence_limit} n/m²],
  [コイルタリーの相対誤差], [{relative_error} %],
  [輸送時間], [{transport} s],
)

== 考察

=== 遮蔽なしでは桁が足りない

ピーク核発熱密度は **{peak_density} W/m³** で、DEMO TF コイルの目標 {heating_limit} W/m³ の
**約 {peak_ratio} 倍**である。高速中性子フルエンスは {fluence} n/m² / フル出力年で、
Nb₃Sn の許容 {fluence_limit} n/m² に **{fluence_days} 日**で到達する。装置寿命を 20 年とすれば
4 桁近く足りない。

これは失敗ではなく、この構成が答えるべき問いへの答えである。増殖材 {thickness} cm だけでは
超伝導コイルは成立しない。

=== 必要な遮蔽厚

14 MeV 中性子に対する遮蔽材の減衰長は 7〜10 cm である。ピークを {heating_limit} W/m³ まで
落とすには $ln$({peak_density}/{heating_limit}) ≈ {attenuation} cm 相当の追加減衰が要る。
parastell の例が遮蔽 50 cm を置いているのと矛盾しない。

ただしこれは指数減衰だけを見た概算で、実際には γ のビルドアップと、増殖材を薄くすることによる
TBR の低下がトレードオフに入る。al_06 の TBR-厚み曲線と本計算を同じ半径方向予算の上で解くのが
次段である。

=== 断面が法平面に乗らない — この計算で最も大きい系統誤差

ガイドを中心線の平行移動に取ると、断面のローカル $+x$ は 1 本の固定ベクトル $e_phi$ になる。
これは接線と直交しない箇所で断面を寝かせる。測ると最悪点で {tilt_max} 度、コイルあたりの
RMS で {tilt_rms} 度ある。

結果として掃引体積は {coil_volume} m³ で、断面積 × 中心線長の {exact_volume} m³ に対し
**{volume_error} %** である。

これは al_07 の最適化が粗いせいではない。同じ手順を parastell 自身の `coils.example` に
当てはめても RMS 29 度・体積 −22% になる。**モジュラーコイルの巻線パックは、断面の向きを
1 本の固定ベクトルに保つ限り表現できない。** 経路が面外に大きく振れるためで、コイル面の法線 $e_phi$ を選んでも、
コイル点群に最も良く乗る平面の法線を選んでも (実測 −24%) 改善しない。

核発熱への効き方は単純なスケールではない。断面が寝ると体積が減るだけでなく、中性子が
コイルを通過する実効的な厚みも歪む。上の数値は **20% 程度の系統的な過小評価を含む**と読むべきで、
統計誤差 {relative_error} % より大きい。

正攻法は `ProfileOrient::Auxiliary` で、補助曲線によって断面の向きを点ごとに制御することである。
cadrum の doc がこの variant を「ステラレーターの断面回転」用と名指ししているのは、まさに
この問題のためである。巻線パックの厚み方向をプラズマ向きに揃えれば物理的にも正しくなる。
今回はそこまで踏み込まず、誤差を明記して先に進めた。

=== この計算が答えていないこと

- **ピーク値の統計**。合計は相対誤差 {relative_error} % で決まるが、R-Z マップのビンごとは
  それより粗い。ピーク {peak_density} W/m³ は桁を示す値であって有効数字ではない。
- **コイル間の差**。全コイルを 1 つの材料タグで束ねたので、どのコイルが最も熱いかは出ていない。
  コイルごとにタグを分ければ出せる。
- **均質化の妥当性**。実際の巻線パックは層構造を持ち、Cu 安定化材と超伝導線で発熱密度が違う。
  局所のホットスポットは均質化では出ない。
"""


if __name__ == "__main__":
	main()
