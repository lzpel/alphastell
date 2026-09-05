import json
import math
import pathlib
from typing import Any

import h5py
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import openmc
from cad_to_dagmc import CadToDagmc

from alphastell import Geometry
import al_10_parastell_cad_to_dagmc_example as al_10

matplotlib.use("Agg")


def main(
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(al_10.__file__).with_suffix(".md").name,
	# 層名 (stem の末尾) → 色。Release previous_steps の parastell 全構造プレビューと同じ割り当て
	colors: dict[str, str] = {
		"chamber": "#9ec9de",  # 真空
		"first_wall": "#6e7176",  # タングステン
		"breeder": "#59a869",  # 増殖材
		"back_wall": "#c08457",  # EUROFER
		"shield": "#4a4e69",  # 炭化タングステン
		"vacuum_vessel": "#b0b7bd",  # SS316
		"magnets": "#e08a2e",  # コイル
	},
	rotate_z: float = math.pi,  # 扇形 (第 1 象限) を回して、切断面が 4 面図のカメラに向くようにする [rad]
	tolerance: float = 1.0,  # cad_to_dagmc の cadquery バックエンドの三角形化の許容差 [cm]。gmsh はホストでは落ちる
	angular_tolerance: float = 0.2,  # 同 角度許容差 [rad]
	particles: int = 10000,
	batches: int = 30,  # 論文と同じ 30 万粒子
	tally_xy: int = 50,  # 発熱マップの水平分割数
	tally_z: int = 25,  # 同 鉛直分割数
	nfp: int = 4,
	dt_energy: float = 17.6e6,  # DT 反応 1 回あたりの発生エネルギー [eV]
	neutron_energy: float = 14.1e6,
	joule_per_ev: float = 1.602176634e-19,
) -> dict[str, Any]:
	summary = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))  # al_10 が書いた寸法・体積・線源の要約
	rate = summary["source"]["rate"]  # 扇形 1 つ分の中性子発生率 [n/s]

	# --- STEP を読んで 4 面図と DAGMC にする ---------------------------------------------
	layers, combined = [], None
	for step in sorted(out.parent.glob("*parastell*.step")):
		name = step.stem.rsplit(".", 1)[-1]
		with open(step, "rb") as f:
			geometry = Geometry.read_step(f).color(colors.get(name, "gray"))
		with open(step.with_suffix(".png"), "wb") as f:
			geometry.rotate(rad_z=rotate_z).write_png(f)
		layers.append((step, name, len(geometry), sum(geometry.volume()) * 1e-6))
		combined = geometry if combined is None else combined.concat(geometry)
	with open(out.with_suffix(".png"), "wb") as f:
		combined.rotate(rad_z=rotate_z).write_png(f)
	h5m = dagmc(layers, out.with_suffix(".h5m"), tolerance, angular_tolerance)

	# --- 輸送 ------------------------------------------------------------------------
	mats = al_10.materials()
	source = openmc.IndependentSource(
		space=openmc.stats.MeshSpatial(
			openmc.UnstructuredMesh(str(out.parent / summary["source"]["h5m"]), "moab"),
			np.load(out.parent / summary["source"]["strengths"]),
			volume_normalized=False,
		),
		energy=openmc.stats.Discrete([neutron_energy], [1.0]),
	)
	result = run(h5m, source, mats, out.with_suffix(".openmc"), particles, batches, (tally_xy, tally_xy, tally_z))
	names = [material.name for material in mats]
	heating = {name: result["heating"][name] * rate * joule_per_ev * nfp * 1e-6 for name in names}  # MW 全周
	voxel = float(np.prod(result["mesh"].width)) * 1e-6  # ボクセル体積 [m³]
	heating_map = result["map_heating"] * joule_per_ev * rate / voxel  # [W/m³]
	tritium_map = result["map_tritium"] * rate / voxel  # [T/s/m³]
	source_map = source_density(out.parent / summary["source"]["h5m"], result["mesh"]) / voxel  # [n/s/m³] = T の消費
	for name in names:
		print(f"{name:14s} {heating[name]:9.3f} MW")
	print(f"TBR = {result['tbr']:.4f} +/- {result['tbr_error']:.4f}  lost {result['lost']}  transport {result['t_run']:.0f} s")
	print(f"tritium balance {(tritium_map - source_map).sum() * voxel * nfp:.3e} T/s (expected (TBR-1) S = {(result['tbr'] - 1) * rate * nfp:.3e})")

	figure_heating, figure_tritium = plot_tally(result["mesh"], heating_map, tritium_map, source_map)
	figure_heating.savefig(out.with_suffix(".heating.png"), dpi=150, bbox_inches="tight")
	figure_tritium.savefig(out.with_suffix(".tritium.png"), dpi=150, bbox_inches="tight")
	plt.close(figure_heating)
	plt.close(figure_tritium)

	# --- Markdown レポート。PDF 化は make al-101 が md2pdf.py で行う ----------------------
	parameters = summary["parameters"]
	fields = {
		"combined_png": out.with_suffix(".png").name,
		"heating_png": out.with_suffix(".heating.png").name,
		"tritium_png": out.with_suffix(".tritium.png").name,
		"wall_s": parameters["wall_s"],
		"first_wall": parameters["first_wall"],
		"back_wall": parameters["back_wall"],
		"shield": parameters["shield"],
		"vacuum_vessel": parameters["vacuum_vessel"],
		"breeder_min": min(min(row) for row in parameters["breeder"]),
		"breeder_max": max(max(row) for row in parameters["breeder"]),
		"magnet_width": parameters["magnet_width"],
		"magnet_thickness": parameters["magnet_thickness"],
		"source_cfs": parameters["source_cfs"],
		"source_theta": parameters["source_theta"],
		"source_phi": parameters["source_phi"],
		"n_tets": summary["source"]["n_tets"],
		"tolerance": tolerance,
		"angular_tolerance": angular_tolerance,
		"particles": particles,
		"batches": batches,
		"nfp": nfp,
		"rate": rate,
		"fusion_power": rate * nfp * dt_energy * joule_per_ev * 1e-9,  # GW 全周
		"neutron_power": rate * nfp * neutron_energy * joule_per_ev * 1e-6,  # MW 全周
		"plasma_volume": summary["source"]["plasma_volume"] * nfp,
		"chamber_volume": summary["volumes"]["chamber"] * nfp,
		"tbr": result["tbr"],
		"tbr_error": result["tbr_error"],
		"heating_total": sum(heating.values()),
		"peak_density": float(heating_map.max()),
		"tritium_surplus": (result["tbr"] - 1.0) * rate * nfp,
		"lost": result["lost"],
		"t_run": result["t_run"],
		"layer_rows": "".join(
			f"| {name} | {colors.get(name, 'gray')} | {n} | {summary['volumes'][name]:.3f} | {volume:.3f} | {heating.get(name, 0.0):.4g} |\n"
			for _, name, n, volume in layers
		),
		"figures": "\n\n".join(f"![{step.with_suffix('.png').name}]({step.with_suffix('.png').name})" for step, _, _, _ in layers),
	}
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	print(f"{out}: {out.stat().st_size} bytes")
	return fields


def source_density(source_h5m: pathlib.Path, mesh: openmc.RegularMesh) -> np.ndarray:
	"""parastell の四面体線源を直交メッシュにビン分けした強度 [n/s per voxel]。tet の重心にその強度を置く。

	MOAB の h5m を h5py で読む (ホストに pymoab は無い)。連結は 1 始まりの節点 id。
	"""
	with h5py.File(source_h5m) as f:
		nodes = f["tstt/nodes/coordinates"][()]
		tets = f["tstt/elements/Tet4/connectivity"][()] - int(f["tstt/nodes/coordinates"].attrs["start_id"])
		strengths = f["tstt/elements/Tet4/tags/Source Strength"][()]
	centroids = nodes[tets].mean(axis=1)
	edges = [np.linspace(lo, hi, n + 1) for lo, hi, n in zip(mesh.lower_left, mesh.upper_right, mesh.dimension)]
	return np.histogramdd(centroids, bins=edges, weights=strengths)[0]


def plot_tally(
	mesh: openmc.RegularMesh,
	heating: np.ndarray,  # ボクセル平均の核発熱密度 [W/m³]
	tritium: np.ndarray,  # (n,Xt) のトリチウム生成密度 [T/s/m³]
	source: np.ndarray,  # 線源密度 [n/s/m³]。DT 反応 1 回 = 中性子 1 個 = T 消費 1 個
	phi: float = math.pi / 4,  # 収支を描くポロイダル断面のトロイダル角 [rad]。扇形の中央
	half_width: float = math.radians(2.0),  # 断面に入れるボクセルの角度幅 (片側) [rad]
) -> tuple[matplotlib.figure.Figure, matplotlib.figure.Figure]:
	"""発熱の 3D 散布図と、トリチウム収支 (生成 − 消費) のポロイダル断面。

	収支の全体積積分は (TBR − 1) × 線源強度に等しい。負側がプラズマの DT、正側が LiPb の Li-6, Li-7 で、
	同じ単位・同じカラーバーに乗せることで、燃やす量に対して作る量がどこでどれだけ上回るかが読める。
	断面は φ 平均ではなく φ=phi の薄い帯。ステラレータは断面が φ で回るので、平均すると別の φ の層が混ざる。
	"""
	lower, upper = np.asarray(mesh.lower_left) / 100, np.asarray(mesh.upper_right) / 100  # [m]
	widths = (upper - lower) / np.asarray(mesh.dimension)
	centers = np.meshgrid(*[lower[k] + (np.arange(mesh.dimension[k]) + 0.5) * widths[k] for k in range(3)], indexing="ij")

	figure_heating = plt.figure(figsize=(8.5, 7.0))
	axes = figure_heating.add_subplot(projection="3d")
	mask = heating > 0
	image = axes.scatter(centers[0][mask], centers[1][mask], centers[2][mask], c=heating[mask], norm=matplotlib.colors.LogNorm(), s=4)
	figure_heating.colorbar(image, ax=axes, label="nuclear heating [W/m^3]", shrink=0.7)
	axes.set_box_aspect(upper - lower)
	axes.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]", title="nuclear heating, neutrons and photons")

	# φ=phi の帯に中心が落ちるボクセルを (R, Z) に並べる。3D 散布は手前が奥を隠すので収支はこちらで描く
	balance = tritium - source
	angle = np.arctan2(centers[1], centers[0])
	band = (np.abs(angle - phi) < half_width) & ((tritium > 0) | (source > 0))
	radius, height = np.hypot(centers[0], centers[1])[band], centers[2][band]
	r_edges = np.arange(radius.min() - widths[0] / 2, radius.max() + widths[0], widths[0])
	z_edges = np.linspace(lower[2], upper[2], mesh.dimension[2] + 1)
	total = np.histogram2d(radius, height, bins=[r_edges, z_edges], weights=balance[band])[0]
	count = np.histogram2d(radius, height, bins=[r_edges, z_edges])[0]
	mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
	limit = float(np.nanmax(np.abs(mean)))
	figure_tritium, axes = plt.subplots(figsize=(7.5, 5.5))
	image = axes.pcolormesh(
		r_edges, z_edges, mean.T, cmap="RdBu_r", norm=matplotlib.colors.SymLogNorm(linthresh=limit * 1e-3, vmin=-limit, vmax=limit)
	)
	figure_tritium.colorbar(image, ax=axes, label="tritium balance, bred minus burnt [T/s/m^3]")
	axes.set(xlabel="R [m]", ylabel="Z [m]", title=f"tritium burnt (DT, blue) and bred (Li-6, Li-7, red) at phi = {math.degrees(phi):.0f} deg", aspect="equal")
	return figure_heating, figure_tritium


def dagmc(layers: list[tuple[pathlib.Path, str, int, float]], h5m: pathlib.Path, tolerance: float, angular_tolerance: float) -> pathlib.Path:
	"""層ごとの STEP を 1 つの DAGMC にする。材料タグは層名で、chamber は void。STEP は cm なので scale は 1。

	gmsh バックエンドはこの STEP に対してホストでは面を出さない (file 経由は 0 面、in memory はアクセス違反) ので cadquery で三角形化する。
	imprint (層の共有面のブーリアン) は 24 ソリッドで 10 分を超えても終わらないので切る。共有面は層ごとに別々に三角形化されるので lost を数える。
	"""
	cad = CadToDagmc()
	for step, name, n_solids, _ in layers:
		cad.add_stp_file(str(step), material_tags=["vacuum" if name == "chamber" else name] * n_solids)
	cad.export_dagmc_h5m_file(filename=str(h5m), meshing_backend="cadquery", tolerance=tolerance, angular_tolerance=angular_tolerance, imprint=False)
	return h5m


def run(
	h5m: pathlib.Path,
	source: openmc.IndependentSource,
	mats: list[openmc.Material],
	work: pathlib.Path,
	particles: int,
	batches: int,
	dimension: tuple[int, int, int],
) -> dict[str, Any]:
	"""90° 扇形の DAGMC を CSG の回転周期平面で囲み、TBR・層別核加熱 [eV/中性子]・発熱マップを返す。"""
	dagmc_universe = openmc.DAGMCUniverse(str(h5m), auto_geom_ids=True)  # 内部の cell 1 が CSG の cell と衝突する
	lower, upper = (np.asarray(b, dtype=float) for b in dagmc_universe.bounding_box)
	# DAGMC は periodic 未対応なので、φ=0 (y=0) と φ=90° (x=0) の平面を CSG で回転周期にする。
	# bbox の外側 4 面は真空。周期平面と切断面が一致するので lost が出うる
	plane_0 = openmc.YPlane(0.0, boundary_type="periodic")
	plane_90 = openmc.XPlane(0.0, boundary_type="periodic")
	plane_0.periodic_surface = plane_90
	cell = openmc.Cell(region=dagmc_universe.bounding_region(padding_distance=10.0) & +plane_0 & +plane_90, fill=dagmc_universe)

	mesh = openmc.RegularMesh()  # id は自動。線源の非構造メッシュ (id 1) と衝突させない
	mesh.dimension, mesh.lower_left, mesh.upper_right = dimension, lower, upper
	layers = openmc.Tally(name="layers")
	layers.filters = [openmc.MaterialFilter(mats)]
	layers.scores = ["(n,Xt)", "heating"]
	mapped = openmc.Tally(name="map")
	mapped.filters = [openmc.MeshFilter(mesh)]
	mapped.scores = ["heating", "(n,Xt)"]
	settings = openmc.Settings(run_mode="fixed source", source=source, particles=particles, batches=batches)
	settings.photon_transport = True  # FENDL-3.2 に heating-local (MT=901) が無いので、光子も運んで heating で取る
	settings.survival_biasing = True
	settings.max_lost_particles = max(10, particles * batches // 1000)  # 打ち切らず数を報告する
	model = openmc.Model(
		geometry=openmc.Geometry([cell]),
		materials=openmc.Materials(mats),
		settings=settings,
		tallies=openmc.Tallies([layers, mapped]),
	)
	work.mkdir(parents=True, exist_ok=True)
	with openmc.StatePoint(model.run(cwd=work, output=False)) as statepoint:
		values = statepoint.get_tally(name="layers")
		tritium = values.get_values(scores=["(n,Xt)"]).flatten()
		tritium_error = values.get_values(scores=["(n,Xt)"], value="std_dev").flatten()
		heating = values.get_values(scores=["heating"]).flatten()
		# メッシュフィルタのビンは x が最内で回るので order="F" でないと軸が入れ替わる
		grid = statepoint.get_tally(name="map")
		map_heating = grid.get_values(scores=["heating"]).reshape(dimension, order="F")
		map_tritium = grid.get_values(scores=["(n,Xt)"]).reshape(dimension, order="F")
		transport = float(statepoint.runtime["transport"])
	return {
		"tbr": float(tritium.sum()),
		"tbr_error": float(np.sqrt(np.sum(tritium_error**2))),
		"heating": dict(zip([material.name for material in mats], map(float, heating))),
		"map_heating": map_heating,
		"map_tritium": map_tritium,
		"mesh": mesh,
		"lost": len(list(work.glob("particle_*.h5"))),
		"t_run": transport,
	}


TEMPLATE = """# ParaStell 形状で TBR と核加熱を出す (al_10 / al_101)

ParaStell (Moreno, Bader, Wilson 2024) は WISTELL-D の TBR 1.10 を報告しているが計算スクリプトは非公開で、
公開コードで ParaStell 形状から OpenMC で TBR を出した例も無い。ここでは ParaStell 同梱の平衡と同じ層厚で
形状を起こし、論文と同じ材料組成・FENDL 3.2 で TBR と層別核加熱を出す。

役割は 2 本に分かれる。al_10 は `ghcr.io/svalinn/parastell-ci` コンテナの中で ParaStell を動かし、層ごとの STEP と
四面体線源メッシュを書く。al_101 はホストの openmc-anywhere でそれを読み、cad_to_dagmc で DAGMC にして輸送する。
コンテナの conda 版 OpenMC は光子輸送で落ちるので、輸送をホストに置くことで光子込みの核加熱が取れる。

## 方法

### 幾何

ParaStell の `parastell_cad_to_dagmc_example.py` の radial build をそのまま使う。
第一壁の内面は VMEC を s={wall_s} まで外挿した面で、そこから面内法線方向に
第一壁 {first_wall:.0f} cm、増殖層 {breeder_min:.0f}〜{breeder_max:.0f} cm (9×9 の厚さ行列、コイルに近い場所で薄い)、
後壁 {back_wall:.0f} cm、遮蔽 {shield:.0f} cm、真空容器 {vacuum_vessel:.0f} cm を積む。
マグネットは同梱 `coils.example` のフィラメントを {magnet_width:.0f}×{magnet_thickness:.0f} cm の矩形断面で掃引したもの。
1 周期 (90°) だけ作り、cad_to_dagmc (cadquery の三角形化、許容差 {tolerance} cm、角度 {angular_tolerance} rad) で DAGMC にする。

OpenMC の DAGMC は周期境界を受け付けないので、φ=0 と φ=90° の平面を CSG の回転周期境界にして
その中に DAGMC universe を詰める。切断面と CSG 平面が一致するため lost particle が出うるので数を報告する。

![全層を重ねた 4 面図。層ごとの STEP を alphastell で読み、cadrum で描く]({combined_png})

### 材料

論文 Table 1/2 (ARIES-CS の DCLL) の均質化組成を体積分率で混ぜる。
第一壁 He 66 / RAFM 34、増殖層 LiPb 79 / He 8 / SiC 7 / RAFM 6、後壁 RAFM 80 / He 20、
遮蔽 WC 75 / RAFM 15 / He 10、真空容器 RAFM 51 / 水 49、マグネット RAFM 67.4 / Cu 19.3 / Nb3Sn 5.1 / He 4.2 / 絶縁 4。
LiPb は Pb 83 / Li 17 at% で Li6 を 90% 濃縮、密度 9.806 g/cm³。核データは FENDL 3.2。

### 線源

ParaStell の四面体線源メッシュ ({source_cfs}×{source_theta}×{source_phi}、{n_tets} 個の tet) をそのまま使う。
反応率は $n(s)=4.8\\times10^{{20}}(1-s^5)$ m⁻³、$T(s)=11.5(1-s)$ keV の既定プロファイルで、
tet ごとの強度 [n/s] を `MeshSpatial` に渡す。14.1 MeV 単色。

### 輸送

{particles} 粒子 × {batches} バッチ (論文と同じ 30 万)、光子輸送あり、survival biasing あり。
タリーは材料フィルタで層ごとに (n,Xt) と heating、直交メッシュで heating と (n,Xt) を取る。
TBR は全材料の (n,Xt) の和、核加熱は 1 中性子あたりの eV に発生率と周期数 {nfp} を掛けて全周の MW にする。

## 結果

![ボクセル別の核発熱密度 (中性子 + 光子)]({heating_png})

![φ=45° のポロイダル断面でのトリチウム収支。負 (青) はプラズマで DT 反応が T を燃やす密度、正 (赤) は LiPb で Li-6, Li-7 が T を作る密度。全体積の積分が (TBR − 1) × 線源強度になる]({tritium_png})

| 層 | 色 | ソリッド数 | 体積 cadquery [m³/扇形] | 体積 cadrum [m³/扇形] | 核加熱 [MW 全周] |
|:--|:--|--:|--:|--:|--:|
{layer_rows}
| 量 | 値 |
|:--|--:|
| TBR | {tbr:.4f} ± {tbr_error:.4f} |
| 中性子発生率 (扇形) | {rate:.3e} n/s |
| 核融合出力 (全周、17.6 MeV) | {fusion_power:.2f} GW |
| 中性子出力 (全周、14.1 MeV) | {neutron_power:.0f} MW |
| 核加熱の合計 (全周) | {heating_total:.0f} MW |
| 発熱密度のピーク (ボクセル平均) | {peak_density:.3e} W/m³ |
| トリチウムの純増 (TBR − 1) × S (全周) | {tritium_surplus:.3e} T/s |
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
マグネット核加熱は論文の 152 kW と比べられない。コイル配置と平衡が別物で、LCFS からコイルまでの隙間が違うからである。

核融合出力 {fusion_power:.2f} GW は al_09 で VMEC から直接積分した 3.09 GW と突き合わせる値で、
線源 tet の体積和 {plasma_volume:.1f} m³ は VMEC の volume_p 635.7 m³ と突き合わせる値である。

### 核加熱の行き先

核加熱の合計 {heating_total:.0f} MW が中性子出力 {neutron_power:.0f} MW を上回るのは、Li6(n,t) の 4.8 MeV など
発熱反応の分で、エネルギー増倍率に相当する。光子輸送を入れているので、Pb と Fe の捕獲・非弾性散乱で出る
γ 線が落ちる先 (第一壁・遮蔽・真空容器) の発熱も入っている。

### この計算が答えていないこと

- 周期境界の切断面での lost particle ({lost} 個) の TBR への影響。lost は消えるだけなので TBR を下げる向きに効く。
- 水の S(α,β) 熱散乱は入れていない。真空容器の水は TBR にほとんど効かない。
- 論文のように増殖層率を振るスキャンはしていない。1 点だけである。
- 不均質な流路構造は入っていない。均質化組成のままで、これが alphastell 側で変える部分である。

{figures}
"""

if __name__ == "__main__":
	main()
