#!/usr/bin/env -S MSYS_NO_PATHCONV=1 docker run --rm -i -e OPENMC_CROSS_SECTIONS=/work/out/cross_sections/cross_sections.xml -e PATH=/opt/conda/envs/parastell_env/bin:/usr/local/bin:/usr/bin:/bin -v ${PWD}:/work -w /work ghcr.io/svalinn/parastell-ci /opt/conda/envs/parastell_env/bin/python
import json
import os
import pathlib
from typing import Any

import cadquery as cq
import matplotlib
import numpy as np
import openmc
import parastell.parastell as ps


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	coils: pathlib.Path = pathlib.Path("/opt/parastell/examples/coils.example"),  # parastell-ci コンテナ同梱
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
	# 層厚 [cm]。parastell の examples/parastell_cad_to_dagmc_example.py と同じ値
	wall_s: float = 1.08,
	first_wall: float = 5.0,
	back_wall: float = 5.0,
	shield: float = 50.0,
	vacuum_vessel: float = 10.0,
	breeder: list[list[float]] = [
		[75.0, 75.0, 75.0, 25.0, 25.0, 25.0, 75.0, 75.0, 75.0],
		[75.0, 75.0, 75.0, 25.0, 25.0, 75.0, 75.0, 75.0, 75.0],
		[75.0, 75.0, 25.0, 25.0, 75.0, 75.0, 75.0, 75.0, 75.0],
		[65.0, 25.0, 25.0, 65.0, 75.0, 75.0, 75.0, 75.0, 65.0],
		[45.0, 45.0, 75.0, 75.0, 75.0, 75.0, 75.0, 45.0, 45.0],
		[65.0, 75.0, 75.0, 75.0, 75.0, 65.0, 25.0, 25.0, 65.0],
		[75.0, 75.0, 75.0, 75.0, 75.0, 25.0, 25.0, 75.0, 75.0],
		[75.0, 75.0, 75.0, 75.0, 25.0, 25.0, 75.0, 75.0, 75.0],
		[75.0, 75.0, 75.0, 25.0, 25.0, 25.0, 75.0, 75.0, 75.0],
	],
	magnet_width: float = 40.0,
	magnet_thickness: float = 50.0,
	sample_mod: int = 6,
	mesh_cfs: int = 11,
	mesh_theta: int = 61,
	mesh_phi: int = 61,
	min_mesh_size: float = 5.0,
	max_mesh_size: float = 20.0,
	particles: int = 10000,
	batches: int = 30,  # 論文と同じ 30 万粒子
	nfp: int = 4,
	dt_energy: float = 17.6e6,
	neutron_energy: float = 14.1e6,
	joule_per_ev: float = 1.602176634e-19,
) -> dict[str, Any]:
	work = out.with_suffix(".openmc")
	work.mkdir(parents=True, exist_ok=True)
	stellarator, volumes, strengths, plasma_volume = build(
		wout, coils, out, work, wall_s, first_wall, back_wall, shield, vacuum_vessel, breeder,
		magnet_width, magnet_thickness, sample_mod, mesh_cfs, mesh_theta, mesh_phi, min_mesh_size, max_mesh_size,
	)
	rate = float(np.sum(strengths))  # 扇形 1 つ分の中性子発生率 [n/s]
	result = run(work / "dagmc.h5m", work / "source_mesh.h5m", strengths, materials(), work, particles, batches, out)
	layers = ["first_wall", "breeder", "back_wall", "shield", "vac_vessel", "magnets"]
	heating = {name: result["heating"][name] * rate * joule_per_ev * nfp * 1e-6 for name in layers}  # MW 全周
	for name in layers:
		print(f"{name:12s} volume {volumes[name]:8.3f} m3/sector  heating {heating[name]:8.3f} MW")
	print(f"TBR = {result['tbr']:.4f} +/- {result['tbr_error']:.4f}  lost {result['lost']}  transport {result['t_run']:.0f} s")

	fields = {
		"section_png": out.with_suffix(".section.png").name,
		"top_png": out.with_suffix(".top.png").name,
		"wall_s": wall_s,
		"first_wall": first_wall,
		"back_wall": back_wall,
		"shield": shield,
		"vacuum_vessel": vacuum_vessel,
		"breeder_min": min(min(row) for row in breeder),
		"breeder_max": max(max(row) for row in breeder),
		"magnet_width": magnet_width,
		"magnet_thickness": magnet_thickness,
		"mesh_cfs": mesh_cfs,
		"mesh_theta": mesh_theta,
		"mesh_phi": mesh_phi,
		"n_tets": len(strengths),
		"min_mesh_size": min_mesh_size,
		"max_mesh_size": max_mesh_size,
		"particles": particles,
		"batches": batches,
		"nfp": nfp,
		"rate": rate,
		"fusion_power": rate * nfp * dt_energy * joule_per_ev * 1e-9,  # GW 全周
		"neutron_power": rate * nfp * neutron_energy * joule_per_ev * 1e-6,  # MW 全周
		"plasma_volume": plasma_volume * nfp,
		"chamber_volume": volumes["chamber"] * nfp,
		"tbr": result["tbr"],
		"tbr_error": result["tbr_error"],
		"tbr_breeder": result["tbr_breeder"],
		"heating_total": sum(heating.values()),
		"lost": result["lost"],
		"t_run": result["t_run"],
		"rows": "".join(f"| {name} | {volumes[name]:.3f} | {heating[name]:.4g} |\n" for name in layers),
		"volumes": volumes,
		"heating": heating,
		"thickness": {"first_wall": first_wall, "breeder": breeder, "back_wall": back_wall, "shield": shield, "vacuum_vessel": vacuum_vessel},
		"cross_sections": os.environ.get("OPENMC_CROSS_SECTIONS", ""),
		"dagmc": str(work / "dagmc.h5m"),
		"source_mesh": str(work / "source_mesh.h5m"),
	}
	out.with_suffix(".json").write_text(json.dumps(fields, indent=1, ensure_ascii=False), encoding="utf-8")
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	print(f"{out}: {out.stat().st_size} bytes")
	return fields


def build(
	wout: pathlib.Path,
	coils: pathlib.Path,
	out: pathlib.Path,
	work: pathlib.Path,
	wall_s: float,
	first_wall: float,
	back_wall: float,
	shield: float,
	vacuum_vessel: float,
	breeder: list[list[float]],
	magnet_width: float,
	magnet_thickness: float,
	sample_mod: int,
	mesh_cfs: int,
	mesh_theta: int,
	mesh_phi: int,
	min_mesh_size: float,
	max_mesh_size: float,
) -> tuple[ps.Stellarator, dict[str, float], np.ndarray, float]:
	"""parastell で 1 周期分の in-vessel build・マグネット・線源メッシュを作り DAGMC にする。

	層ごとの STEP を out.<層>.step に書き、体積 [m³/扇形] と tet 強度 [n/s] とプラズマ体積 [m³/扇形] を返す。
	"""
	stellarator = ps.Stellarator(str(wout))
	toroidal_angles = np.linspace(0.0, 90.0, 9)
	poloidal_angles = np.linspace(0.0, 360.0, 9)
	uniform = np.ones((len(toroidal_angles), len(poloidal_angles)))
	radial_build = {
		"first_wall": {"thickness_matrix": uniform * first_wall},
		"breeder": {"thickness_matrix": np.array(breeder)},
		"back_wall": {"thickness_matrix": uniform * back_wall},
		"shield": {"thickness_matrix": uniform * shield},
		"vacuum_vessel": {"thickness_matrix": uniform * vacuum_vessel, "mat_tag": "vac_vessel"},
	}
	stellarator.construct_invessel_build(toroidal_angles, poloidal_angles, wall_s, radial_build)
	stellarator.construct_magnets_from_filaments(str(coils), magnet_width, magnet_thickness, 90.0, sample_mod=sample_mod)

	volumes = {}
	solids, tags = stellarator.invessel_build.extract_solids_and_mat_tags()
	for name, solid, tag in zip(stellarator.invessel_build.Components, solids, tags):
		solid.exportStep(str(out.with_suffix(f".{name}.step")))
		volumes[tag if tag != "Vacuum" else name] = solid.Volume() * 1e-6
	magnets = cq.Compound.makeCompound(stellarator.magnet_set.all_coil_solids)
	magnets.exportStep(str(out.with_suffix(".magnets.step")))
	volumes["magnets"] = magnets.Volume() * 1e-6

	stellarator.construct_source_mesh(
		np.linspace(0.0, 1.0, mesh_cfs), np.linspace(0.0, 360.0, mesh_theta), np.linspace(0.0, 90.0, mesh_phi)
	)
	stellarator.export_source_mesh(filename="source_mesh", export_dir=str(work))
	stellarator.build_cad_to_dagmc_model()
	stellarator.export_cad_to_dagmc(filename="dagmc", export_dir=str(work), min_mesh_size=min_mesh_size, max_mesh_size=max_mesh_size)
	strengths = np.asarray(stellarator.source_mesh.strengths, dtype=float)
	plasma_volume = float(np.sum(stellarator.source_mesh.volumes)) * 1e-6
	return stellarator, volumes, strengths, plasma_volume


def materials() -> list[openmc.Material]:
	"""ParaStell 論文 Table 1/2 (ARIES-CS の DCLL) の均質化材料。name が DAGMC の材料タグと一致する。"""

	def constituent_material(
		name: str, density: float, atoms: dict[str, float], percent: str = "ao", enrichment_isotopes: dict[str, float] | None = None
	) -> openmc.Material:
		"""enrichment_isotopes は {"Li6": 90.0} のように同位体名 → 存在比 (percent と同じ単位)。"""
		material = openmc.Material(name=name)
		for element, fraction in atoms.items():
			target = next((k for k in enrichment_isotopes or {} if k.rstrip("0123456789") == element), None)
			enrichment = {"enrichment": enrichment_isotopes[target], "enrichment_target": target, "enrichment_type": percent} if target else {}
			material.add_element(element, fraction, percent, **enrichment)
		material.set_density("g/cm3", density)
		return material

	helium = constituent_material("He", 0.00572, {"He": 100.0})
	rafm = constituent_material("RAFM", 7.8, {"Fe": 89.5, "Cr": 9.0, "W": 1.5}, "wo")
	lipb = constituent_material("LiPb", 9.806, {"Pb": 83.0, "Li": 17.0}, enrichment_isotopes={"Li6": 90.0})
	sic = constituent_material("SiC", 3.21, {"Si": 50.0, "C": 50.0})
	wc = constituent_material("WC", 15.63, {"W": 50.0, "C": 50.0})
	water = constituent_material("water", 1.0, {"H": 66.7, "O": 33.3})
	copper = constituent_material("Cu", 8.96, {"Cu": 100.0})
	nb3sn = constituent_material("Nb3Sn", 8.74, {"Nb": 75.0, "Sn": 25.0})
	silica = constituent_material("SiO2", 2.65, {"O": 66.7, "Si": 33.3})
	polyimide = constituent_material("polyimide", 1.42, {"C": 69.11, "O": 20.92, "N": 7.33, "H": 2.64}, "wo")
	insulator = openmc.Material.mix_materials([silica, polyimide], [0.6, 0.4], "wo", name="insulator")

	mix = openmc.Material.mix_materials
	return [
		mix([helium, rafm], [0.66, 0.34], "vo", name="first_wall"),
		mix([lipb, helium, sic, rafm], [0.79, 0.08, 0.07, 0.06], "vo", name="breeder"),
		mix([rafm, helium], [0.80, 0.20], "vo", name="back_wall"),
		mix([wc, rafm, helium], [0.75, 0.15, 0.10], "vo", name="shield"),
		mix([rafm, water], [0.51, 0.49], "vo", name="vac_vessel"),
		mix([rafm, copper, nb3sn, helium, insulator], [0.674, 0.193, 0.051, 0.042, 0.04], "vo", name="magnets"),
	]


def run(
	h5m: pathlib.Path,
	source_h5m: pathlib.Path,
	strengths: np.ndarray,
	mats: list[openmc.Material],
	work: pathlib.Path,
	particles: int,
	batches: int,
	out: pathlib.Path,
) -> dict[str, Any]:
	"""90° 扇形の DAGMC を CSG の回転周期平面で囲み、TBR と層別核加熱 [eV/中性子] を返す。"""
	openmc.reset_auto_ids()
	dagmc = openmc.DAGMCUniverse(str(h5m), auto_geom_ids=True)  # 内部の cell 1 が CSG の cell と衝突する
	lower, upper = dagmc.bounding_box
	# DAGMC は periodic 未対応なので、φ=0 (y=0) と φ=90° (x=0) の平面を CSG で回転周期にする
	plane_0 = openmc.YPlane(0.0, boundary_type="periodic")
	plane_90 = openmc.XPlane(0.0, boundary_type="periodic")
	plane_0.periodic_surface = plane_90
	radius = float(np.hypot(max(abs(lower[0]), abs(upper[0])), max(abs(lower[1]), abs(upper[1])))) * 1.05
	cylinder = openmc.ZCylinder(r=radius, boundary_type="vacuum")
	bottom = openmc.ZPlane(float(lower[2]) - 10.0, boundary_type="vacuum")
	top = openmc.ZPlane(float(upper[2]) + 10.0, boundary_type="vacuum")
	cell = openmc.Cell(region=+plane_0 & +plane_90 & -cylinder & +bottom & -top, fill=dagmc)

	mesh = openmc.UnstructuredMesh(str(source_h5m), "moab")
	source = openmc.IndependentSource(
		space=openmc.stats.MeshSpatial(mesh, strengths, volume_normalized=False),
		energy=openmc.stats.Discrete([14.1e6], [1.0]),
	)
	tally = openmc.Tally(name="layers")
	tally.filters = [openmc.MaterialFilter(mats)]
	tally.scores = ["(n,Xt)", "heating"]
	settings = openmc.Settings(run_mode="fixed source", source=source, particles=particles, batches=batches)
	# parastell-ci の conda 版 OpenMC 0.15.3 は光子輸送を入れると CSG の鉄球でも segfault する。
	# heating は中性子 KERMA だけで、光子が運ぶ分は落ちる (FENDL-3.2 には MT=901 が無いので heating-local も使えない)
	settings.photon_transport = False
	settings.survival_biasing = True
	# 切断面と CSG 平面が一致するので lost が出うる。打ち切らず数を報告する
	settings.max_lost_particles = max(10, particles * batches // 1000)
	model = openmc.Model(
		geometry=openmc.Geometry([cell]),
		materials=openmc.Materials(mats),
		settings=settings,
		tallies=openmc.Tallies([tally]),
	)
	plot(model, lower, upper, out)
	statepoint_path = model.run(cwd=work, output=False)
	with openmc.StatePoint(statepoint_path) as statepoint:
		values = statepoint.get_tally(name="layers")
		tritium = values.get_values(scores=["(n,Xt)"]).flatten()
		tritium_error = values.get_values(scores=["(n,Xt)"], value="std_dev").flatten()
		heating = values.get_values(scores=["heating"]).flatten()
		transport = float(statepoint.runtime["transport"])
	names = [material.name for material in mats]
	return {
		"tbr": float(tritium.sum()),
		"tbr_error": float(np.sqrt(np.sum(tritium_error**2))),
		"tbr_breeder": float(tritium[names.index("breeder")]),
		"heating": dict(zip(names, map(float, heating))),
		"lost": len(list(work.glob("particle_*.h5"))),
		"t_run": transport,
	}


def plot(model: openmc.Model, lower: np.ndarray, upper: np.ndarray, out: pathlib.Path) -> None:
	"""φ=0⁺ のポロイダル断面 (xz) と赤道面の上面図 (xy) を材料色で描く。"""
	center_r = (float(lower[0]) + float(upper[0])) / 2
	span = max(float(upper[0]) - float(lower[0]), float(upper[2]) - float(lower[2])) * 1.1
	views = [
		("section", "xz", (center_r, 1.0, 0.0), (span, span)),
		("top", "xy", ((float(lower[0]) + float(upper[0])) / 2, (float(lower[1]) + float(upper[1])) / 2, 0.0), (span, span)),
	]
	palette = matplotlib.colormaps["tab10"]
	colors = {material: tuple(int(255 * c) for c in palette(i)[:3]) for i, material in enumerate(model.materials)}
	for name, basis, origin, width in views:
		axes = model.plot(origin=origin, width=width, pixels=(900, 900), basis=basis, color_by="material", colors=colors, legend=True)
		axes.set_title(f"{basis} slice through {tuple(round(o) for o in origin)} [cm]")
		axes.figure.savefig(out.with_suffix(f".{name}.png"), dpi=150, bbox_inches="tight")


TEMPLATE = """# ParaStell 形状で TBR を出す (al_10)

ParaStell (Moreno, Bader, Wilson 2024) は WISTELL-D の TBR 1.10 を報告しているが計算スクリプトは非公開で、
公開コードで ParaStell 形状から OpenMC で TBR を出した例も無い。ここでは ParaStell 同梱の平衡と同じ層厚で
形状を起こし、論文と同じ材料組成・FENDL 3.2 で TBR と層別核加熱を出す。後続の alphastell 側の形状と
突き合わせる基準値として、層ごとの STEP と体積、線源メッシュ、材料定義を残す。

このスクリプトは `ghcr.io/svalinn/parastell-ci` コンテナの中で動く (shebang で docker を起動する)。

## 方法

### 幾何

ParaStell の `parastell_cad_to_dagmc_example.py` の radial build をそのまま使う。
第一壁の内面は VMEC を s={wall_s} まで外挿した面で、そこから面内法線方向に
第一壁 {first_wall:.0f} cm、増殖層 {breeder_min:.0f}〜{breeder_max:.0f} cm (9×9 の厚さ行列、コイルに近い場所で薄い)、
後壁 {back_wall:.0f} cm、遮蔽 {shield:.0f} cm、真空容器 {vacuum_vessel:.0f} cm を積む。
マグネットは同梱 `coils.example` のフィラメントを {magnet_width:.0f}×{magnet_thickness:.0f} cm の矩形断面で掃引したもの。
1 周期 (90°) だけ作り、cad_to_dagmc (要素 {min_mesh_size:.0f}〜{max_mesh_size:.0f} cm) で DAGMC にする。

OpenMC の DAGMC は周期境界を受け付けないので、φ=0 と φ=90° の平面を CSG の回転周期境界にして
その中に DAGMC universe を詰める。切断面と CSG 平面が一致するため lost particle が出うるので数を報告する。

### 材料

論文 Table 1/2 (ARIES-CS の DCLL) の均質化組成を体積分率で混ぜる。
第一壁 He 66 / RAFM 34、増殖層 LiPb 79 / He 8 / SiC 7 / RAFM 6、後壁 RAFM 80 / He 20、
遮蔽 WC 75 / RAFM 15 / He 10、真空容器 RAFM 51 / 水 49、マグネット RAFM 67.4 / Cu 19.3 / Nb3Sn 5.1 / He 4.2 / 絶縁 4。
LiPb は Pb 83 / Li 17 at% で Li6 を 90% 濃縮、密度 9.806 g/cm³。核データは FENDL 3.2。

### 線源

ParaStell の四面体線源メッシュ ({mesh_cfs}×{mesh_theta}×{mesh_phi}、{n_tets} 個の tet) をそのまま使う。
反応率は $n(s)=4.8\\times10^{{20}}(1-s^5)$ m⁻³、$T(s)=11.5(1-s)$ keV の既定プロファイルで、
tet ごとの強度 [n/s] を `MeshSpatial` に渡す。14.1 MeV 単色。

### 輸送

{particles} 粒子 × {batches} バッチ (論文と同じ 30 万)、survival biasing あり。
タリーは材料フィルタで層ごとに (n,Xt) と heating を取る。
TBR は全材料の (n,Xt) の和、核加熱は 1 中性子あたりの eV に発生率と周期数 {nfp} を掛けて全周の MW にする。
光子輸送は入れていない。parastell-ci コンテナの conda 版 OpenMC 0.15.3 は光子輸送を有効にすると
CSG の鉄球ですら segfault するためで、ホストの openmc-anywhere (al_09) では同じ FENDL 3.2 で通る。
したがって核加熱は中性子 KERMA のみで、二次光子が運ぶ分 (鋼材では過半) を含まない。

## 結果

![φ=0 直後のポロイダル断面。内側から chamber (void)、第一壁、増殖層、後壁、遮蔽、真空容器、外にマグネット。]({section_png})

![赤道面の上面図。90° 扇形 1 周期分。]({top_png})

| 層 | 体積 [m³/扇形] | 中性子核加熱 [MW 全周] |
|:--|--:|--:|
{rows}
| 量 | 値 |
|:--|--:|
| TBR | {tbr:.4f} ± {tbr_error:.4f} |
| 中性子発生率 (扇形) | {rate:.3e} n/s |
| 核融合出力 (全周、17.6 MeV) | {fusion_power:.2f} GW |
| 中性子出力 (全周、14.1 MeV) | {neutron_power:.0f} MW |
| 中性子核加熱の合計 (全周) | {heating_total:.0f} MW |
| 線源 tet の体積和 (全周) | {plasma_volume:.1f} m³ |
| chamber (s≤{wall_s}) の体積 (全周) | {chamber_volume:.1f} m³ |
| lost particle | {lost} |
| 輸送時間 | {t_run:.0f} s |

## 考察

### 論文との比較

論文の設計点 (全厚 100%、増殖層 60%) は TBR 1.10、目標 1.05。ここでの TBR {tbr:.3f} はそれより高い。
平衡が WISTELL-D ではなく ParaStell 同梱の別解 (R=11.1 m、a=1.7 m、B=5.9 T) である上に、
例の厚さ行列は 81 点のうち 53 点が {breeder_max:.0f} cm で、コイルに近い場所だけ {breeder_min:.0f} cm に落とす。
論文の設計点は使える隙間の 60% を増殖層に回すので薄い場所が広く、その分 TBR が低い。
Li6 90% 濃縮の LiPb を 75 cm 積めば 1.2〜1.3 は均質モデルの通常の値で、論文の 1.05 目標には余裕がある。
マグネット核加熱は論文の 152 kW と比べられない。コイル配置と平衡が別物で、LCFS からコイルまでの隙間が違うからである。

核融合出力 {fusion_power:.2f} GW は al_09 で VMEC から直接積分した 3.09 GW と突き合わせる値で、
線源 tet の体積和 {plasma_volume:.1f} m³ は VMEC の volume_p 635.7 m³ と突き合わせる値である。
どちらも ParaStell の線源メッシュが alphastell の積分と同じ物理量を見ていることの確認になる。

### alphastell 側と突き合わせるときに使うもの

- 層ごとの STEP `al_10_parastell_tbr.<層>.step` と体積 (`al_10_parastell_tbr.json` の volumes)。
  同じ厚さ行列 (json の thickness) を alphastell の `point_normal(φ, θ, {wall_s}, False)` の面内法線で積めば
  同じ層になるはずで、体積差が形状生成器の差になる。
- 線源 `{source_mesh}` と材料定義 (この script の `materials()`)。これを共有すれば TBR と層別核加熱の差は形状だけになる。
- DAGMC `{dagmc}`。alphastell 側の h5m と三角形数や lost の数を比べる。

### この計算が答えていないこと

- 周期境界の切断面での lost particle ({lost} 個) の TBR への影響。lost は消えるだけなので TBR を下げる向きに効く。
- 光子が運ぶ核加熱。層別核加熱は中性子分のみで、合計が中性子出力 {neutron_power:.0f} MW を下回るのはそのため。
  光子込みの値が要るならホストの openmc-anywhere で同じ `{dagmc}` と `{source_mesh}` を回す。
- 水の S(α,β) 熱散乱は入れていない。真空容器の水は TBR にほとんど効かない。
- 論文のように増殖層率を振るスキャンはしていない。1 点だけである。
- 不均質な流路構造は入っていない。均質化組成のままで、これが alphastell 側で変える部分である。
"""

if __name__ == "__main__":
	main()
