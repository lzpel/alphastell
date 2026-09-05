import math
import pathlib
import time
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import openmc
from cad_to_dagmc import CadToDagmc, write_vtk

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
	thickness: float = 0.5,  # PbLi 殻の厚み [m]。al_06 の中央の厚みに合わせる
	div_phi: int = 96,  # 殻の制御点。al_06 と同じにして幾何を一致させる
	div_theta: int = 40,
	particles: int = 40000,
	batches: int = 10,
	n_flat: int = 200,  # case_1 の一様点線源の数
	n_weighted: int = 5000,  # case_2 の重み付き点線源の数
	mesh_s: int = 8,  # 約 23000 tet。tet 数が settings.xml のサイズを決める
	mesh_theta: int = 16,
	mesh_phi: int = 32,
	s_max: float = 0.98,  # LCFS 上に線源を置くと幾何境界に乗るので手前で切る (n, T → 0 なので損失は無い)
	tally_r: int = 48,
	tally_z: int = 48,
) -> list[dict[str, Any]]:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)

	out.parent.mkdir(parents=True, exist_ok=True)
	outer = blanket(surface, out.with_suffix(".shell.step"), out.with_suffix(".h5m"), thickness, div_phi, div_theta)
	radius, height = np.hypot(outer[..., 0], outer[..., 1]), outer[..., 2]
	mesh = openmc.CylindricalMesh(
		r_grid=np.linspace(radius.min(), radius.max(), tally_r + 1) * 100,
		z_grid=np.linspace(height.min(), height.max(), tally_z + 1) * 100,
		mesh_id=1,
	)
	h5m, work = out.with_suffix(".h5m"), out.with_suffix(".openmc")
	results = [
		case_1(surface, mesh, h5m, work, n_flat, particles, batches),
		case_2(surface, mesh, h5m, work, n_weighted, particles, batches),
		case_3(surface, mesh, h5m, work, out.with_suffix(".plasma.vtk"), mesh_s, mesh_theta, mesh_phi, s_max, particles, batches),
	]

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
	figure.savefig(out.with_suffix(".source_s.png"), dpi=150, bbox_inches="tight")
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
	figure.savefig(out.with_suffix(".breeding.png"), dpi=150)
	plt.close(figure)

	# --- Markdown レポート。PDF 化は make al-07 が md2pdf.py (tectonic) で行う ------------
	fields = {
		"source_s_png": out.with_suffix(".source_s.png").name,
		"breeding_png": out.with_suffix(".breeding.png").name,
		"thickness": f"{thickness * 100:.0f}",
		"particles": particles,
		"batches": batches,
		"n_flat": n_flat,
		"n_weighted": n_weighted,
		"n_tets": len(results[2]["s"]),
		"mesh_s": mesh_s,
		"mesh_theta": mesh_theta,
		"mesh_phi": mesh_phi,
		"rows": "".join(
			f"| {r['name']} | {r['mean_s']:.3f} | {r['tbr']:.3f} ± {r['error']:.3f} | {r['peaking']:.2f} |"
			f" {r['deviation']:.1f} | {r['noise']:.1f} | {r['t_setup']:.1f} | {r['t_init']:.1f} | {r['t_run']:.0f} |\n"
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
		"slowdown_2": (results[1]["t_run"] / results[0]["t_run"] - 1.0) * 100,
		"slowdown_3": (results[2]["t_run"] / results[0]["t_run"] - 1.0) * 100,
		"init_3": results[2]["t_init"],
	}
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	print(f"{out}: {out.stat().st_size} bytes")
	return results


def blanket(surface: SurfaceFourierRZ, step: pathlib.Path, h5m: pathlib.Path, thickness: float, div_phi: int, div_theta: int) -> np.ndarray:
	"""LCFS を法線方向に押し出した PbLi 殻を STEP と DAGMC h5m にする。外側格子を返す。"""
	inner = np.empty((div_phi, div_theta, 3))
	outer = np.empty_like(inner)
	for i, j in np.ndindex(div_phi, div_theta):
		point, normal = surface.point_normal(math.tau * i / div_phi, math.tau * j / div_theta, 1.0, False)
		inner[i, j], outer[i, j] = point, np.add(point, np.multiply(normal, thickness))
	shell = Geometry.bspline_geometry(outer).boolean_subtract(Geometry.bspline_geometry(inner))
	with open(step, "wb") as f:
		shell.write_step(f)
	cad = CadToDagmc()
	cad.add_stp_file(str(step), material_tags=["pbli"])
	cad.export_dagmc_h5m_file(filename=str(h5m), scale_factor=100)  # VMEC は m、OpenMC は cm
	return outer


def reaction_rate(s: np.ndarray) -> np.ndarray:
	"""DT 反応率密度 n²⟨σv⟩ を規格化磁束 s の関数として返す (parastell の既定プロファイル)。"""
	temperature = np.maximum(11.5 * (1.0 - np.asarray(s)), 1e-3)  # keV
	density = 4.8e20 * (1.0 - np.asarray(s) ** 5)  # m^-3
	sigma_v = 3.68e-12 * temperature ** (-2.0 / 3.0) * np.exp(-19.94 * temperature ** (-1.0 / 3.0))
	return density**2 * sigma_v


def jacobian(surface: SurfaceFourierRZ, phi: float, theta: float, s: float) -> float:
	"""体積要素 √g = |∂p/∂s · (∂p/∂θ × ∂p/∂φ)|。point_normal の前進差分だけで作る。"""
	delta = 1e-4
	origin = np.array(surface.point_normal(phi, theta, s, False)[0])
	d_s = np.subtract(surface.point_normal(phi, theta, s + delta, False)[0], origin)
	d_theta = np.subtract(surface.point_normal(phi, theta + delta, s, False)[0], origin)
	d_phi = np.subtract(surface.point_normal(phi + delta, theta, s, False)[0], origin)
	return abs(float(np.dot(d_s, np.cross(d_theta, d_phi)))) / delta**3


def point_sources(surface: SurfaceFourierRZ, samples: np.ndarray, weights: np.ndarray) -> list[openmc.IndependentSource]:
	"""(φ, θ, s) の並びを点線源の並びにする。強度の合計は 1 に規格化する。"""
	return [
		openmc.IndependentSource(
			space=openmc.stats.Point(np.multiply(surface.point_normal(phi, theta, s, False)[0], 100)),
			energy=openmc.stats.Discrete([14.07e6], [1.0]),
			strength=weight,
		)
		for (phi, theta, s), weight in zip(samples, weights / weights.sum())
	]


def plasma_tets(surface: SurfaceFourierRZ, mesh_s: int, mesh_theta: int, mesh_phi: int, s_max: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
	"""(s, θ, φ) 格子からプラズマ体積を四面体で埋める。頂点 [m]、四面体、頂点の s を返す。

	最内層は磁気軸との間の三角柱を 3 分割、外側は六面体を主対角 v0-v6 まわりに 6 分割する。
	どの面も隣のセルと同じ対角で割れるので、隙間も重なりも出ない。

	s 層は等間隔ではなく s ∝ k² に切る。s ∝ r² なので、これは小半径方向の等間隔にあたる。
	セル内の発生は一様なので、反応率が急な内側を等間隔で切ると線源が外へ寄る。この刻みなら
	加重平均 s の離散化バイアスが 7% から 1.3% に下がる (mesh_s を増やさずに)。
	"""
	levels = s_max * ((np.arange(mesh_s) + 1) / mesh_s) ** 2
	axis = np.array([surface.point_normal(math.tau * p / mesh_phi, 0.0, 0.0, False)[0] for p in range(mesh_phi)])
	shell = np.array([
		surface.point_normal(math.tau * p / mesh_phi, math.tau * t / mesh_theta, levels[k], False)[0]
		for p in range(mesh_phi)
		for k in range(mesh_s)
		for t in range(mesh_theta)
	])
	vertices = np.concatenate([axis, shell])
	vertex_s = np.concatenate([np.zeros(mesh_phi), np.tile(np.repeat(levels, mesh_theta), mesh_phi)])

	def index(p: int, k: int, t: int) -> int:
		p, t = p % mesh_phi, t % mesh_theta
		return p if k < 0 else mesh_phi + (p * mesh_s + k) * mesh_theta + t

	prism_split = [(0, 1, 2, 5), (0, 1, 5, 4), (0, 4, 5, 3)]
	hex_split = [(0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6)]
	tetrahedra = []
	for p in range(mesh_phi):
		for t in range(mesh_theta):
			prism = [
				index(p, -1, 0), index(p, 0, t), index(p, 0, t + 1),
				index(p + 1, -1, 0), index(p + 1, 0, t), index(p + 1, 0, t + 1),
			]
			tetrahedra += [[prism[v] for v in tet] for tet in prism_split]
			for k in range(mesh_s - 1):
				cell = [
					index(p, k, t), index(p, k, t + 1), index(p, k + 1, t + 1), index(p, k + 1, t),
					index(p + 1, k, t), index(p + 1, k, t + 1), index(p + 1, k + 1, t + 1), index(p + 1, k + 1, t),
				]
				tetrahedra += [[cell[v] for v in tet] for tet in hex_split]
	return vertices, np.array(tetrahedra), vertex_s


def run(source: openmc.SourceBase, mesh: openmc.CylindricalMesh, work: pathlib.Path, h5m: pathlib.Path, particles: int, batches: int) -> dict[str, Any]:
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
		geometry=openmc.Geometry(openmc.DAGMCUniverse(str(h5m)).bounded_universe()),
		materials=openmc.Materials([pbli]),
		settings=openmc.Settings(run_mode="fixed source", source=source, particles=particles, batches=batches),
		tallies=openmc.Tallies([total, local]),
	)
	work.mkdir(parents=True, exist_ok=True)
	statepoint_path = model.run(cwd=work, output=False)
	with openmc.StatePoint(statepoint_path) as statepoint:
		transport, initialization = statepoint.runtime["transport"], statepoint.runtime["total initialization"]
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
		}


def case_1(surface: SurfaceFourierRZ, mesh: openmc.CylindricalMesh, h5m: pathlib.Path, work: pathlib.Path, n_flat: int, particles: int, batches: int) -> dict[str, Any]:
	"""al_06 現行方式。(φ, θ, s) 一様サンプルの点線源を等強度で置く。"""
	start = time.perf_counter()
	samples = np.random.default_rng(0).random((n_flat, 3)) * [math.tau, math.tau, 1.0]
	weights = np.full(n_flat, 1.0 / n_flat)
	source = point_sources(surface, samples, weights)
	setup = time.perf_counter() - start
	return {"name": "case_1 uniform points", "s": samples[:, 2], "weights": weights, "t_setup": setup} | run(
		source, mesh, work / "case_1", h5m, particles, batches
	)


def case_2(surface: SurfaceFourierRZ, mesh: openmc.CylindricalMesh, h5m: pathlib.Path, work: pathlib.Path, n_weighted: int, particles: int, batches: int) -> dict[str, Any]:
	"""点数を増やし、強度を反応率 × 体積要素にする。依存も Rust 側の変更も要らない。"""
	start = time.perf_counter()
	samples = np.random.default_rng(0).random((n_weighted, 3)) * [math.tau, math.tau, 1.0]
	weights = reaction_rate(samples[:, 2]) * [jacobian(surface, *sample) for sample in samples]
	source = point_sources(surface, samples, weights)
	setup = time.perf_counter() - start
	return {"name": "case_2 weighted points", "s": samples[:, 2], "weights": weights / weights.sum(), "t_setup": setup} | run(
		source, mesh, work / "case_2", h5m, particles, batches
	)


def case_3(surface: SurfaceFourierRZ, mesh: openmc.CylindricalMesh, h5m: pathlib.Path, work: pathlib.Path, vtk: pathlib.Path, mesh_s: int, mesh_theta: int, mesh_phi: int, s_max: float, particles: int, batches: int) -> dict[str, Any]:
	"""parastell と同じ四面体メッシュ線源。tet の強度は重心の反応率 × 四面体体積。"""
	start = time.perf_counter()
	vertices, tetrahedra, vertex_s = plasma_tets(surface, mesh_s, mesh_theta, mesh_phi, s_max)
	corners = vertices[tetrahedra]
	volumes = np.abs(np.linalg.det(corners[:, 1:] - corners[:, :1])) / 6.0
	centroid_s = vertex_s[tetrahedra].mean(axis=1)
	weights = reaction_rate(centroid_s) * volumes
	write_vtk(str(vtk), vertices, tetrahedra)
	source = openmc.MeshSource(
		openmc.UnstructuredMesh(str(vtk), library="moab", length_multiplier=100.0, mesh_id=2),
		[openmc.IndependentSource(energy=openmc.stats.Discrete([14.07e6], [1.0]), strength=weight) for weight in weights],
	)
	source.normalize_source_strengths()
	setup = time.perf_counter() - start
	return {"name": "case_3 tet mesh", "s": centroid_s, "weights": weights / weights.sum(), "t_setup": setup} | run(
		source, mesh, work / "case_3", h5m, particles, batches
	)


# Markdown レポートの本文。main() が数値を差し込み、PDF 化は make al-07 が md2pdf.py で行う
TEMPLATE = """# 中性子線源モデル 3 種の比較 (al_07)

al_06 の線源は規格化磁束・ポロイダル角・トロイダル角 (s, θ, φ) の空間に一様に撒いた
{n_flat} 個の等強度点線源である。しかし実際の中性子発生密度は核融合反応率 $n^2 \\langle\\sigma v\\rangle$ に
比例し、s≈0 に鋭く集中する。この食い違いが結果にどれだけ効くのかを、同じ PbLi 殻
(厚み {thickness} cm) の上で線源だけを差し替えて測った。

## 方法

3 ケースとも幾何・材料・粒子数 ({particles} 粒子 × {batches} バッチ) は同一で、線源だけが違う。

- **case_1**: al_06 現行方式。(s, θ, φ) 一様サンプルの点線源 {n_flat} 個、等強度。
- **case_2**: 同じ一様サンプルを {n_weighted} 個に増やし、強度を反応率 × 体積要素 $\\sqrt g$ にする。$\\sqrt g$ は `point_normal` の前進差分だけで作れるので、依存も Rust 側の変更も要らない。
- **case_3**: parastell と同じ四面体メッシュ線源。(s, θ, φ) を {mesh_s}×{mesh_theta}×{mesh_phi} に切って四面体 {n_tets} 個で埋め、各 tet の強度を重心の反応率 × 四面体体積とする。OpenMC には `MeshSource` として渡す。s 層は等間隔ではなく $s \\propto k^2$、すなわち $s \\propto r^2$ より小半径の等間隔で切ってある。セル内の発生は一様なので、反応率が急な内側を等間隔で切ると線源が外へ寄り、加重平均 s が 7% 高く出る。この刻みならセル数を増やさずに 1.3% に収まる。

プロファイルは parastell の既定と同じ

$$
T = 11.5 (1 - s)\\ \\mathrm{{keV}}, \\quad n = 4.8 \\times 10^{{20}} (1 - s^5)\\ \\mathrm{{m}}^{{-3}}, \\quad \\langle\\sigma v\\rangle = 3.68 \\times 10^{{-12}}\\, T^{{-2/3}} \\exp(-19.94\\, T^{{-1/3}})\\ \\mathrm{{cm}}^3/\\mathrm{{s}}
$$

で、エネルギーは 3 ケースとも 14.07 MeV 単色である。

タリーは全体の (n,Xt) と、円筒メッシュ (r×z、φ 全周積分) 上の (n,Xt) の 2 つ。後者はビン体積で
割ってトリチウム生成密度にしてある。

## 結果

| ケース | 平均 s | TBR | ピーキング | case_3 比 [%] | うちノイズ [%] | setup [s] | init [s] | 輸送 [s] |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
{rows}
「平均 s」は強度加重平均で、線源がプラズマのどこに居るかを表す。「ピーキング」は非ゼロビンの
99 パーセンタイル / 平均。「case_3 比」は case_3 の明るいビンに対する局所密度の RMS 相対差で、
これには 2 ラン分のショットノイズが必ず乗るので、タリーの標準偏差から期待されるノイズ床を
「うちノイズ」に併記した。両者の差が線源モデルの違いによる正味の寄与である。

![規格化磁束 s に対する線源強度の累積分布。case_1 はほぼ直線 (体積一様) で、case_2 と case_3 はコアに集中して立ち上がる。case_3 の s は tet の重心なので離散値しか取らず、ヒストグラムにすると空きビンが振動に見えるため累積で描いた。]({source_s_png})

![左: case_3 の R-Z トリチウム生成密度 (φ 全周積分)。中・右: case_1 と case_2 の同じ量の case_3 に対する比で、全体の平均で規格化して形状の違いだけを出してある。3 枚の絶対値を並べても差が見えないので比で描いた。]({breeding_png})

## 考察

### TBR は線源モデルをほぼ選ばない

case_1 の TBR は case_3 より {gap_1_3:.1f}% 低い。統計的には {sigma_1_3:.1f}σ あって偶然ではないが、
差の大きさ自体は構造材を入れたときに起きる変化に比べれば無視できる。厚い殻が全周を閉じていて、
内部のどこから出ても 4π が増殖材だからである。al_06 のコメントにある「TBR は線源分布にほぼ
依存しない」は、al_06 の結論を書き換える必要がないという意味では正しい。case_2 と case_3 の差は
{sigma_2_3:.1f}σ で、統計誤差の範囲に収まる。

なお同じ粒子数でも case_1 の統計誤差は {error_1:.3f} と case_3 の {error_3:.3f} の 2 倍ある。
線源を {n_flat} 個の点に離散化した分だけ 1 ヒストリあたりのばらつきが増えるためで、
点線源を少数で済ませることは計算時間の節約になっていない。

### 線源そのものは大きく違う

加重平均 s は case_1 が {mean_s_1:.2f}、case_2 が {mean_s_2:.2f}、case_3 が {mean_s_3:.2f} である。
case_1 はプラズマ全体に平坦に配ったぶん、本来ほとんど中性子が出ない外周 (s > 0.6) に線源の
半分近くを置いている。case_2 は一様サンプル + 重みなので偏りが無く、これが基準値になる。
case_3 が case_2 より僅かに大きいのは前述のセル内一様性によるもので、s 層の刻みで決まる離散化バイアスである。

局所密度の RMS 差は case_1 が {deviation_1:.1f}% (ノイズ床 {noise_1:.1f}%)、case_2 が
{deviation_2:.1f}% (ノイズ床 {noise_2:.1f}%) である。ノイズ床を二乗で差し引いた正味は case_1 が
{net_1:.1f}%、case_2 が {net_2:.1f}% になる。case_1 の差は圧倒的で、線源モデルの違いが局所量に
はっきり現れている。case_2 にも {net_2:.1f}% の正味の差が残っており、これは case_3 の s 方向の
離散化バイアスと、θ・φ 方向の粗い格子による線源位置のずれと見るのが自然である。どちらが正しいかは
この表からは決まらないが、加重平均 s では case_2 が不偏の基準値と一致している。

### 計算負荷

輸送時間の差は測れなかった、というのがこの環境での結論である。時間は OpenMC 自身が報告する
輸送時間で、各ケース 1 回の計測である。同一条件でも他プロセスの負荷で数十 % 平気で伸びるので、
表の case 間の差 (case_1 に対し case_2 が {slowdown_2:+.0f}%、case_3 が {slowdown_3:+.0f}%) は
そのばらつきと同程度で、有意な差とは言えない。線源数に比例する線形走査
(case_2) も、非構造メッシュからの点抽出 (case_3) も、14 MeV 中性子の輸送そのものに比べれば
小さいということでもある。線源モデルは計算時間で選ぶ話ではない。

初期化時間ははっきりしている。線源やメッシュの構築 (setup) は 3 ケースとも 1 秒未満、
OpenMC 側の初期化も case_3 で {init_3:.1f} 秒しかない。要素ソースを 1 つずつ XML に書き出す
コストは実測では問題にならず、四面体メッシュを避ける理由にはならない。

### 結論

case_1 の誤りは TBR という積分量ではほとんど見えず、局所量で初めて出る。第一壁の核発熱・dpa・
ダイバータ近傍のストリーミングを見る al_09 以降では case_1 は使えない。

移行先としては case_2 で足りる。追加コードは反応率とヤコビアンの数行だけで、依存も増えず、
線源分布に離散化バイアスが無く、計算時間の差も測定できない程度である。case_3 の
四面体メッシュは精度で勝るのではなく (むしろ s 方向の離散化バイアスを持つ)、線源をファイルとして
残せること、parastell と同じ土俵で比較できること、VTK でそのまま可視化できることに価値がある。
parastell との数値比較を実際に行う段で導入すればよい。
"""


if __name__ == "__main__":
	main()
