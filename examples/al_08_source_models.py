#!/usr/bin/env python3
"""中性子線源モデル 3 種を同じ PbLi 殻で比較する (al_08)。

al_06 の線源は (φ, θ, s) 一様・等強度の点線源 200 個で、核融合反応率が s≈0 に集中するという
物理と食い違っている。厚い全周ブランケットの TBR は線源分布にほぼ鈍感なので al_06 の結論は
変わらないが、al_10 以降で不均質 WCLL の局所量 (壁負荷・核発熱) を見る段では効いてくる。

    case_1  al_06 現行方式         : 一様サンプル 200 点、等強度
    case_2  重み付き点線源         : 一様サンプル 5000 点、強度 = 反応率 × 体積要素
    case_3  四面体メッシュ線源     : parastell と同じ方式。tet ごとに反応率 × 体積

精度・計算時間・実装量の実測でどれに移行すべきかを決めるのが目的。

    make al-08
"""

import math
import pathlib
import time
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openmc
import typst
from cad_to_dagmc import CadToDagmc, write_vtk

from alphastell import SurfaceFourierRZ, Geometry

WOUT = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc"
OUT = pathlib.Path("out")
WORK = OUT / "al_08_openmc"
STEP = OUT / "al_08_shell.step"
H5M = OUT / "al_08.h5m"
VTK = OUT / "al_08_plasma.vtk"

THICKNESS = 0.5  # m。al_06 の中央の厚みに合わせる
DIV_PHI, DIV_THETA = 96, 40  # 殻の制御点。al_06 と同じにして幾何を一致させる
PARTICLES, BATCHES = 40000, 10
REPEAT = 2  # 実行時間は他プロセスの負荷で数十 % 平気で伸びるので、繰り返して最小値を採る
N_FLAT, N_WEIGHTED = 200, 5000
MESH_S, MESH_THETA, MESH_PHI = 8, 16, 32  # 約 23000 tet。tet 数が settings.xml のサイズを決める
S_MAX = 0.98  # LCFS 上に線源を置くと幾何境界に乗るので手前で切る (n, T → 0 なので損失は無い)
TALLY_R, TALLY_Z = 48, 48
ENERGY = openmc.stats.Discrete([14.07e6], [1.0])

with open(WOUT, "rb") as f:
	surface = SurfaceFourierRZ.load(f)


def blanket() -> np.ndarray:
	"""LCFS を法線方向に押し出した PbLi 殻を STEP と DAGMC h5m にする。外側格子を返す。"""
	inner = np.empty((DIV_PHI, DIV_THETA, 3))
	outer = np.empty_like(inner)
	for i, j in np.ndindex(DIV_PHI, DIV_THETA):
		point, normal = surface.point_normal(math.tau * i / DIV_PHI, math.tau * j / DIV_THETA, 1.0, False)
		inner[i, j], outer[i, j] = point, np.add(point, np.multiply(normal, THICKNESS))
	shell = Geometry.bspline_geometry(outer).boolean_subtract(Geometry.bspline_geometry(inner))
	with open(STEP, "wb") as f:
		shell.write_step(f)
	cad = CadToDagmc()
	cad.add_stp_file(str(STEP), material_tags=["pbli"])
	cad.export_dagmc_h5m_file(filename=str(H5M), scale_factor=100)  # VMEC は m、OpenMC は cm
	return outer


def reaction_rate(s: np.ndarray) -> np.ndarray:
	"""DT 反応率密度 n²⟨σv⟩ を規格化磁束 s の関数として返す (parastell の既定プロファイル)。"""
	temperature = np.maximum(11.5 * (1.0 - np.asarray(s)), 1e-3)  # keV
	density = 4.8e20 * (1.0 - np.asarray(s) ** 5)  # m^-3
	sigma_v = 3.68e-12 * temperature ** (-2.0 / 3.0) * np.exp(-19.94 * temperature ** (-1.0 / 3.0))
	return density**2 * sigma_v


def jacobian(phi: float, theta: float, s: float) -> float:
	"""体積要素 √g = |∂p/∂s · (∂p/∂θ × ∂p/∂φ)|。point_normal の前進差分だけで作る。"""
	delta = 1e-4
	origin = np.array(surface.point_normal(phi, theta, s, False)[0])
	d_s = np.subtract(surface.point_normal(phi, theta, s + delta, False)[0], origin)
	d_theta = np.subtract(surface.point_normal(phi, theta + delta, s, False)[0], origin)
	d_phi = np.subtract(surface.point_normal(phi + delta, theta, s, False)[0], origin)
	return abs(float(np.dot(d_s, np.cross(d_theta, d_phi)))) / delta**3


def point_sources(samples: np.ndarray, weights: np.ndarray) -> list[openmc.IndependentSource]:
	"""(φ, θ, s) の並びを点線源の並びにする。強度の合計は 1 に規格化する。"""
	return [
		openmc.IndependentSource(
			space=openmc.stats.Point(np.multiply(surface.point_normal(phi, theta, s, False)[0], 100)),
			energy=ENERGY,
			strength=weight,
		)
		for (phi, theta, s), weight in zip(samples, weights / weights.sum())
	]


def plasma_tets() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
	"""(s, θ, φ) 格子からプラズマ体積を四面体で埋める。頂点 [m]、四面体、頂点の s を返す。

	最内層は磁気軸との間の三角柱を 3 分割、外側は六面体を主対角 v0-v6 まわりに 6 分割する。
	どの面も隣のセルと同じ対角で割れるので、隙間も重なりも出ない。

	s 層は等間隔ではなく s ∝ k² に切る。s ∝ r² なので、これは小半径方向の等間隔にあたる。
	セル内の発生は一様なので、反応率が急な内側を等間隔で切ると線源が外へ寄る。この刻みなら
	加重平均 s の離散化バイアスが 7% から 1.3% に下がる (MESH_S を増やさずに)。
	"""
	levels = S_MAX * ((np.arange(MESH_S) + 1) / MESH_S) ** 2
	axis = np.array([surface.point_normal(math.tau * p / MESH_PHI, 0.0, 0.0, False)[0] for p in range(MESH_PHI)])
	shell = np.array([
		surface.point_normal(math.tau * p / MESH_PHI, math.tau * t / MESH_THETA, levels[k], False)[0]
		for p in range(MESH_PHI)
		for k in range(MESH_S)
		for t in range(MESH_THETA)
	])
	vertices = np.concatenate([axis, shell])
	vertex_s = np.concatenate([np.zeros(MESH_PHI), np.tile(np.repeat(levels, MESH_THETA), MESH_PHI)])

	def index(p: int, k: int, t: int) -> int:
		p, t = p % MESH_PHI, t % MESH_THETA
		return p if k < 0 else MESH_PHI + (p * MESH_S + k) * MESH_THETA + t

	prism_split = [(0, 1, 2, 5), (0, 1, 5, 4), (0, 4, 5, 3)]
	hex_split = [(0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6)]
	tetrahedra = []
	for p in range(MESH_PHI):
		for t in range(MESH_THETA):
			prism = [
				index(p, -1, 0), index(p, 0, t), index(p, 0, t + 1),
				index(p + 1, -1, 0), index(p + 1, 0, t), index(p + 1, 0, t + 1),
			]
			tetrahedra += [[prism[v] for v in tet] for tet in prism_split]
			for k in range(MESH_S - 1):
				cell = [
					index(p, k, t), index(p, k, t + 1), index(p, k + 1, t + 1), index(p, k + 1, t),
					index(p + 1, k, t), index(p + 1, k, t + 1), index(p + 1, k + 1, t + 1), index(p + 1, k + 1, t),
				]
				tetrahedra += [[cell[v] for v in tet] for tet in hex_split]
	return vertices, np.array(tetrahedra), vertex_s


def run(source: openmc.SourceBase, mesh: openmc.CylindricalMesh, name: str) -> dict[str, Any]:
	"""線源だけを差し替えて同じ幾何・同じ粒子数で回す。TBR と R-Z マップと実行時間を返す。"""
	# bounded_universe は id を 10000 番台に固定で振るので、ケースごとに呼ぶと衝突して IDWarning が出る
	openmc.reset_auto_ids()
	pbli = openmc.Material(name="pbli")
	pbli.add_element("Li", 17.0, "ao", enrichment=90.0, enrichment_target="Li6", enrichment_type="ao")
	pbli.add_element("Pb", 83.0, "ao")
	pbli.set_density("g/cm3", 9.4)

	total = openmc.Tally(name="tbr")
	total.scores = ["(n,Xt)"]
	local = openmc.Tally(name="map")
	local.filters = [openmc.MeshFilter(mesh)]
	local.scores = ["(n,Xt)"]

	model = openmc.Model(
		geometry=openmc.Geometry(openmc.DAGMCUniverse(str(H5M)).bounded_universe()),
		materials=openmc.Materials([pbli]),
		settings=openmc.Settings(run_mode="fixed source", source=source, particles=PARTICLES, batches=BATCHES),
		tallies=openmc.Tallies([total, local]),
	)
	work = WORK / name
	work.mkdir(parents=True, exist_ok=True)
	# 乱数種が同じなので繰り返しても結果は変わらない。時間だけを見る
	timing = []
	for _ in range(REPEAT):
		statepoint_path = model.run(cwd=work, output=False)
		with openmc.StatePoint(statepoint_path) as statepoint:
			timing.append((statepoint.runtime["transport"], statepoint.runtime["total initialization"]))
	transport, initialization = min(timing)
	spread = (max(timing)[0] / transport - 1.0) * 100
	with openmc.StatePoint(statepoint_path) as statepoint:
		integral = statepoint.get_tally(name="tbr")
		mapped = statepoint.get_tally(name="map")

		def shape(values: np.ndarray) -> np.ndarray:
			# メッシュフィルタのビンは r が最内で回るので order="F" でないと R と Z が入れ替わる
			return np.squeeze(values.reshape(mesh.dimension, order="F"), axis=1)  # (r, φ, z) の φ を潰す

		return {
			"tbr": float(integral.mean.flat[0]),
			"error": float(integral.std_dev.flat[0]),
			"rz_map": shape(mapped.mean),
			"rz_error": shape(mapped.std_dev),
			"t_run": float(transport),
			"t_init": float(initialization),
			"t_spread": float(spread),
		}


def case_1(mesh: openmc.CylindricalMesh) -> dict[str, Any]:
	"""al_06 現行方式。(φ, θ, s) 一様サンプルの点線源を等強度で置く。"""
	start = time.perf_counter()
	samples = np.random.default_rng(0).random((N_FLAT, 3)) * [math.tau, math.tau, 1.0]
	weights = np.full(N_FLAT, 1.0 / N_FLAT)
	source = point_sources(samples, weights)
	setup = time.perf_counter() - start
	return {"name": "case_1 uniform points", "s": samples[:, 2], "weights": weights, "t_setup": setup} | run(
		source, mesh, "case_1"
	)


def case_2(mesh: openmc.CylindricalMesh) -> dict[str, Any]:
	"""点数を増やし、強度を反応率 × 体積要素にする。依存も Rust 側の変更も要らない。"""
	start = time.perf_counter()
	samples = np.random.default_rng(0).random((N_WEIGHTED, 3)) * [math.tau, math.tau, 1.0]
	weights = reaction_rate(samples[:, 2]) * [jacobian(*sample) for sample in samples]
	source = point_sources(samples, weights)
	setup = time.perf_counter() - start
	return {"name": "case_2 weighted points", "s": samples[:, 2], "weights": weights / weights.sum(), "t_setup": setup} | run(
		source, mesh, "case_2"
	)


def case_3(mesh: openmc.CylindricalMesh) -> dict[str, Any]:
	"""parastell と同じ四面体メッシュ線源。tet の強度は重心の反応率 × 四面体体積。"""
	start = time.perf_counter()
	vertices, tetrahedra, vertex_s = plasma_tets()
	corners = vertices[tetrahedra]
	volumes = np.abs(np.linalg.det(corners[:, 1:] - corners[:, :1])) / 6.0
	centroid_s = vertex_s[tetrahedra].mean(axis=1)
	weights = reaction_rate(centroid_s) * volumes
	write_vtk(str(VTK), vertices, tetrahedra)
	source = openmc.MeshSource(
		openmc.UnstructuredMesh(str(VTK), library="moab", length_multiplier=100.0, mesh_id=2),
		[openmc.IndependentSource(energy=ENERGY, strength=weight) for weight in weights],
	)
	source.normalize_source_strengths()
	setup = time.perf_counter() - start
	return {"name": "case_3 tet mesh", "s": centroid_s, "weights": weights / weights.sum(), "t_setup": setup} | run(
		source, mesh, "case_3"
	)


def main() -> list[dict[str, Any]]:
	OUT.mkdir(parents=True, exist_ok=True)
	outer = blanket()
	radius, height = np.hypot(outer[..., 0], outer[..., 1]), outer[..., 2]
	mesh = openmc.CylindricalMesh(
		r_grid=np.linspace(radius.min(), radius.max(), TALLY_R + 1) * 100,
		z_grid=np.linspace(height.min(), height.max(), TALLY_Z + 1) * 100,
		mesh_id=1,
	)
	results = [case_1(mesh), case_2(mesh), case_3(mesh)]

	# タリーのビン体積は r とともに増えるので、割って密度にしないと外周が明るく見えるだけになる
	edge_r, edge_z = np.asarray(mesh.r_grid), np.asarray(mesh.z_grid)
	volume = (math.pi * np.diff(edge_r**2))[:, None] * np.diff(edge_z)[None, :]
	for result in results:
		density = result["rz_map"] / volume
		alive = density[density > 0]
		result["density"] = density
		result["peaking"] = float(np.percentile(alive, 99) / alive.mean())
		result["mean_s"] = float(np.average(result["s"], weights=result["weights"]))
	# case_3 を基準に、統計の乗っているビンだけで局所量のずれを測る。2 ラン分のショットノイズが
	# 必ず乗るので、タリーの std_dev から期待されるノイズ床も出して切り分ける
	bright = results[-1]["density"] > 0.1 * results[-1]["density"].max()
	scatter = results[-1]["rz_error"][bright] / results[-1]["rz_map"][bright]
	for result in results:
		ratio = result["density"][bright] / results[-1]["density"][bright]
		own = result["rz_error"][bright] / np.maximum(result["rz_map"][bright], 1e-30)
		result["deviation"] = float(np.sqrt(np.mean((ratio / ratio.mean() - 1.0) ** 2)) * 100)
		result["noise"] = 0.0 if result is results[-1] else float(np.sqrt(np.mean(own**2 + scatter**2)) * 100)
		print(
			f"{result['name']}: TBR = {result['tbr']:.3f} +/- {result['error']:.3f}"
			f"  setup {result['t_setup']:.1f} s  init {result['t_init']:.1f} s  transport {result['t_run']:.0f} s"
		)

	# --- 図 -------------------------------------------------------------------
	# case_3 の s は tet の重心なので離散値しか取らない。ヒストグラムにすると空きビンが
	# 振動に見えるので、ビン分割の要らない累積分布で描く
	figure, axes = plt.subplots(figsize=(6.0, 4.0))
	for result in results:
		order = np.argsort(result["s"])
		axes.plot(result["s"][order], np.cumsum(result["weights"][order]), label=result["name"])
	axes.set(
		xlabel="normalized flux s",
		ylabel="cumulative source fraction",
		title="Where the neutrons are born",
		xlim=(0.0, 1.0),
		ylim=(0.0, 1.0),
	)
	axes.legend()
	axes.grid(alpha=0.3)
	figure.savefig(OUT / "al_08_source_s.png", dpi=150, bbox_inches="tight")
	plt.close(figure)

	# 絶対値は 3 枚並べてもほぼ同じに見えるので、基準 1 枚と case_3 との比 2 枚にする
	figure, panels = plt.subplots(1, 3, figsize=(11.0, 4.6), sharey=True, layout="constrained")
	extent = [edge_r[0] / 100, edge_r[-1] / 100, edge_z[0] / 100, edge_z[-1] / 100]
	reference = results[-1]["density"]
	absolute = panels[0].imshow(reference.T, origin="lower", extent=extent, aspect="equal")
	panels[0].set(xlabel="R [m]", ylabel="Z [m]", title=f"{results[-1]['name']} (reference)")
	figure.colorbar(absolute, ax=panels[0], location="bottom", label="tritium production density [a.u.]")
	for panel, result in zip(panels[1:], results[:2]):
		ratio = np.where(bright, result["density"] / np.maximum(reference, 1e-30), np.nan)
		image = panel.imshow(
			(ratio / np.nanmean(ratio)).T, origin="lower", extent=extent, vmin=0.7, vmax=1.3, cmap="coolwarm", aspect="equal"
		)
		panel.set(xlabel="R [m]", title=f"{result['name']} / case_3")
	figure.colorbar(image, ax=list(panels[1:]), location="bottom", label="ratio to case_3")
	figure.savefig(OUT / "al_08_breeding.png", dpi=150)
	plt.close(figure)

	# --- PDF レポート ---------------------------------------------------------
	template = pathlib.Path(__file__).with_name("al_08_report.typ").read_text(encoding="utf-8")
	fields = {
		"thickness": f"{THICKNESS * 100:.0f}",
		"particles": PARTICLES,
		"batches": BATCHES,
		"n_flat": N_FLAT,
		"n_weighted": N_WEIGHTED,
		"n_tets": len(results[2]["s"]),
		"mesh_s": MESH_S,
		"mesh_theta": MESH_THETA,
		"mesh_phi": MESH_PHI,
		"rows": "".join(
			f"  [{r['name']}], [{r['mean_s']:.3f}], [{r['tbr']:.3f} ± {r['error']:.3f}], [{r['peaking']:.2f}],"
			f" [{r['deviation']:.1f}], [{r['noise']:.1f}], [{r['t_setup']:.1f}], [{r['t_init']:.1f}], [{r['t_run']:.0f}],\n"
			for r in results
		),
		"gap_1_3": (results[2]["tbr"] / results[0]["tbr"] - 1.0) * 100,
		"sigma_1_3": abs(results[0]["tbr"] - results[2]["tbr"]) / math.hypot(results[0]["error"], results[2]["error"]),
		"sigma_2_3": abs(results[1]["tbr"] - results[2]["tbr"]) / math.hypot(results[1]["error"], results[2]["error"]),
		"deviation_1": results[0]["deviation"],
		"deviation_2": results[1]["deviation"],
		"noise_1": results[0]["noise"],
		"noise_2": results[1]["noise"],
		"net_1": math.sqrt(max(results[0]["deviation"] ** 2 - results[0]["noise"] ** 2, 0.0)),
		"net_2": math.sqrt(max(results[1]["deviation"] ** 2 - results[1]["noise"] ** 2, 0.0)),
		"mean_s_1": results[0]["mean_s"],
		"mean_s_2": results[1]["mean_s"],
		"mean_s_3": results[2]["mean_s"],
		"error_1": results[0]["error"],
		"error_3": results[2]["error"],
		"repeat": REPEAT,
		"spread": max(r["t_spread"] for r in results),
		"slowdown_2": (results[1]["t_run"] / results[0]["t_run"] - 1.0) * 100,
		"slowdown_3": (results[2]["t_run"] / results[0]["t_run"] - 1.0) * 100,
		"init_3": results[2]["t_init"],
	}
	(OUT / "al_08_report.typ").write_text(template.format(**fields), encoding="utf-8")
	typst.compile(OUT / "al_08_report.typ", output=OUT / "al_08_report.pdf")
	print(f"{OUT / 'al_08_report.pdf'}: {(OUT / 'al_08_report.pdf').stat().st_size} bytes")
	return results


if __name__ == "__main__":
	main()
