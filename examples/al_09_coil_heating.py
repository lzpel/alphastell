#!/usr/bin/env python3
"""モジュラーコイルの核発熱 (al_09)。

al_08 の stage-2 最適化 + guided spines 掃引で導体ソリッドを起こし、al_07 の重み付き線源 (case_2) で
中性子を飛ばして、増殖材 (PbLi) 50 cm だけを挟んだコイルが浴びる核発熱と高速中性子フルエンスを出す。
遮蔽体は入れない。「遮蔽がどれだけ要るか」を決めるための下限構成である。

旧 al_10 ドラフト (PR #80) は Up 法の掃引で断面が寝て (最大 84 度、体積 -18%) DAGMC が粒子を
ロストしたため止まっていた。断面の向きは nearest 射影 + LCFS 法線 guide (cadrum 0.8.18 の
Auxiliary) で解決済みなので、その再構成である。

核融合出力は固定値を置かず VMEC 平衡から積分する。プラズマ体積が VMEC の volume_p と一致することが
その積分の検証になる。

	make al-09
"""

import math
import pathlib
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import openmc
from cad_to_dagmc import CadToDagmc

from al_07_source_models import jacobian, point_sources, reaction_rate
from al_07_source_models import surface as lcfs
from al_08_coil_geometry import guided_spines, make_surface, optimize_coil, sweep_guided_spines
from alphastell import Geometry

JOULE_PER_EV = 1.602176634e-19
DT_ENERGY = 17.6e6  # DT 反応 1 回あたりの発生エネルギー [eV]。出力の換算に使う
FAST = 0.1e6  # 高速中性子の下限 [eV]。Nb3Sn のフルエンス制限がこの区間で定義される
YEAR = 365.25 * 24 * 3600  # フル出力年 [s]
HEATING_LIMIT = 450.0  # DEMO TF コイルのピーク核発熱密度の設計目標 [W/m^3]
FLUENCE_LIMIT = 1e22  # Nb3Sn の高速中性子フルエンス許容 [n/m^2]


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
	width: float = 0.40,  # 導体断面のトロイダル幅 [m]。al_08 / al_081 と同じ parastell 準拠の値
	height: float = 0.50,  # 導体断面の半径方向厚み [m]。同上
	thickness: float = 0.5,  # PbLi 殻の厚み [m]。al_06 の中央、al_07 と同じ
	n_source: int = 5000,  # 重み付き点線源の点数。al_07 の case_2 と同じ
	particles: int = 40000,
	batches: int = 10,
	tally_xy: int = 50,  # 3D 発熱マップの水平分割数
	tally_z: int = 25,  # 同 鉛直分割数
) -> dict[str, Any]:
	out.parent.mkdir(parents=True, exist_ok=True)
	surface = make_surface(wout)
	result = optimize_coil(surface)
	# コイルが増殖材に食い込んでいたら黙って壊れた h5m ができるので、ここで止める
	clearance = result["curve_surface_distance"] - height / 2 - thickness
	if clearance <= 0.0:
		raise ValueError(f"coils reach {result['curve_surface_distance']:.2f} m from the LCFS, which overlaps the {thickness} m blanket by {-clearance:.2f} m")

	# --- 幾何: guided spines 掃引のコイルと法線オフセットの増殖材殻 --------------------
	spines = guided_spines(wout, [coil.curve.gamma().tolist() for coil in result["coils"]])
	solids = sweep_guided_spines([-height / 2, -width / 2, height / 2, -width / 2, height / 2, width / 2, -height / 2, width / 2], spines)
	shell, outer = blanket(thickness)
	for geometry, path in ((solids, out.with_suffix(".coils.step")), (shell, out.with_suffix(".shell.step"))):
		with open(path, "wb") as f:
			geometry.write_step(f)
	with open(out.with_suffix(".geometry.png"), "wb") as f:
		shell.concat(solids).write_png(f)  # boolean_union は 33 体で分オーダーかかる。描画に結合は不要

	# 断面積 x 中心線長との突き合わせ。guided 掃引の既知水準は -7〜-4%
	volumes = solids.volume()
	exact = [width * height * float(np.linalg.norm(np.diff(np.array(s)[:, :3], axis=0, append=[s[0][:3]]), axis=1).sum()) for s in spines]
	volume_error = [(v / e - 1.0) * 100 for v, e in zip(volumes, exact)]
	print(f"swept volume error vs area x length {min(volume_error):+.1f}..{max(volume_error):+.1f} %")

	cad = CadToDagmc()
	cad.add_stp_file(str(out.with_suffix(".shell.step")), material_tags=["pbli"])
	cad.add_stp_file(str(out.with_suffix(".coils.step")), material_tags=[f"coil{i:02d}" for i in range(len(solids))])
	cad.export_dagmc_h5m_file(filename=str(out.with_suffix(".h5m")), scale_factor=100)  # VMEC は m、OpenMC は cm
	print(f"{out.with_suffix('.h5m')}: {len(solids)} coils + shell")

	# --- 線源: al_07 case_2 の重み付き点線源と、W 換算のための核融合出力 -----------------
	samples = np.random.default_rng(0).random((n_source, 3)) * [math.tau, math.tau, 1.0]
	volume_elements = np.array([jacobian(*sample) for sample in samples])
	power = fusion_power(samples, volume_elements)
	print(f"plasma volume {power['volume']:.1f} m^3 (VMEC volume_p 635.7), P_fus {power['power'] / 1e9:.2f} GW, S {power['rate']:.3e} n/s")
	source = point_sources(samples, reaction_rate(samples[:, 2]) * volume_elements)

	# --- 輸送とタリー -----------------------------------------------------------------
	# 3D 散布図用の直交メッシュ。コイル点列の外接箱に断面の張り出しぶんの余白を足す
	points = np.array(spines)[..., :3].reshape(-1, 3)
	lower, upper = points.min(axis=0) - height, points.max(axis=0) + height
	mesh = openmc.RegularMesh(mesh_id=1)
	mesh.dimension = (tally_xy, tally_xy, tally_z)
	mesh.lower_left = lower * 100
	mesh.upper_right = upper * 100
	pbli, coil_materials = materials(len(solids))
	tally = heating(out.with_suffix(".h5m"), out.with_suffix(".openmc"), source, mesh, pbli, coil_materials, particles, batches)

	# --- 後処理: eV/線源中性子 → W、W/m^3、n/m^2/フル出力年 -----------------------------
	watts = tally["heating"] * JOULE_PER_EV * power["rate"]  # コイル別 [W]
	densities = watts / np.array(volumes)  # コイル別の体積平均 [W/m^3]
	widths = (upper - lower) / np.asarray(mesh.dimension)  # ボクセル寸法 [m]
	density_map = tally["map"] * JOULE_PER_EV * power["rate"] / float(np.prod(widths))  # ボクセル平均 [W/m^3]
	fluences = tally["flux"] / (np.array(volumes) * 1e6) * power["rate"] * 1e4 * YEAR  # コイル別 [n/m^2 / フル出力年]
	relative_error = float(tally["error"].sum() / tally["heating"].sum())
	print(f"coil heating {watts.sum() / 1e6:.2f} MW total, per-coil mean {densities.mean():.0f} W/m^3 ({densities.min():.0f}..{densities.max():.0f}), map peak {density_map.max():.0f} W/m^3, rel err {relative_error:.1%}")
	print(f"fast fluence {fluences.max():.2e} n/m^2 per full power year (hottest coil {int(np.argmax(densities))})")

	# --- 図: ボクセル別発熱密度の 3D 散布図 ---------------------------------------------
	centers = np.meshgrid(*[lower[k] + (np.arange(mesh.dimension[k]) + 0.5) * widths[k] for k in range(3)], indexing="ij")
	mask = density_map > 0
	figure = plt.figure(figsize=(8.5, 7.0))
	axes = figure.add_subplot(projection="3d")
	image = axes.scatter(centers[0][mask], centers[1][mask], centers[2][mask], c=density_map[mask], norm=matplotlib.colors.LogNorm(), s=4)
	figure.colorbar(image, ax=axes, label="nuclear heating [W/m^3]", shrink=0.7)
	axes.set_box_aspect(np.ptp(points, axis=0))
	axes.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]", title=f"coil nuclear heating at {power['power'] / 1e9:.1f} GW fusion")
	figure.savefig(out.with_suffix(".heating.png"), dpi=150, bbox_inches="tight")
	plt.close(figure)

	# --- 図: コイル別の体積平均発熱密度 --------------------------------------------------
	figure, axes = plt.subplots(figsize=(7.5, 4.2))
	axes.bar(range(len(densities)), densities, color="#4a90d9")
	axes.axhline(HEATING_LIMIT, color="#c0392b", linestyle=":", label=f"DEMO TFC target {HEATING_LIMIT:.0f} W/m^3 (peak)")
	axes.set(xlabel="coil index", ylabel="volume-averaged heating [W/m^3]", title="which coil takes the heat", yscale="log")
	axes.legend()
	axes.grid(alpha=0.3, axis="y")
	figure.tight_layout()
	figure.savefig(out.with_suffix(".percoil.png"), dpi=150, bbox_inches="tight")
	plt.close(figure)

	# --- Markdown レポート。PDF 化は make al-09 が md2pdf.py (tectonic) で行う ------------
	fields = {
		"ncoils": result["parameters"]["ncoils"],
		"ncoil_total": len(solids),
		"standoff": f"{result['parameters']['threshold_curve_surface_distance']:.2f}",
		"achieved": f"{result['curve_surface_distance']:.2f}",
		"clearance": f"{clearance:.2f}",
		"width": f"{width * 100:.0f}",
		"height": f"{height * 100:.0f}",
		"thickness": f"{thickness * 100:.0f}",
		"nsample": n_source,
		"particles": particles,
		"batches": batches,
		"transport": f"{tally['transport']:.0f}",
		"volume_mc": f"{power['volume']:.1f}",
		"power": f"{power['power'] / 1e9:.2f}",
		"rate": f"{power['rate']:.2e}",
		"coil_volume": f"{sum(volumes):.1f}",
		"volume_error_min": f"{min(volume_error):+.1f}",
		"volume_error_max": f"{max(volume_error):+.1f}",
		"watts": f"{watts.sum() / 1e6:.2f}",
		"mean_density": f"{densities.mean():.0f}",
		"hot_coil": int(np.argmax(densities)),
		"hot_density": f"{densities.max():.0f}",
		"cold_density": f"{densities.min():.0f}",
		"peak_density": f"{density_map.max():.0f}",
		"peak_ratio": f"{density_map.max() / HEATING_LIMIT:.0f}",
		"heating_limit": f"{HEATING_LIMIT:.0f}",
		"relative_error": f"{relative_error * 100:.1f}",
		"fluence": f"{fluences.max():.2e}",
		"fluence_limit": f"{FLUENCE_LIMIT:.0e}",
		"fluence_days": f"{FLUENCE_LIMIT / fluences.max() * 365.25:.0f}",
		"attenuation": f"{math.log(density_map.max() / HEATING_LIMIT) * 8.5:.0f}",
		"out_heating_png": out.with_suffix(".heating.png").name,
		"out_percoil_png": out.with_suffix(".percoil.png").name,
		"out_geometry_png": out.with_suffix(".geometry.png").name,
	}
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")
	print(f"{out}: {out.stat().st_size} bytes")
	return fields

def blanket(
	thickness: float,  # PbLi 殻の厚み [m]
	div_phi: int = 96,  # 制御点。al_06 / al_07 と同じにして幾何を揃える
	div_theta: int = 40,
) -> tuple[Geometry, np.ndarray]:
	"""LCFS を法線方向に押し出した PbLi 殻。al_06 と同じ作り方。外側格子も返す。"""
	inner = np.empty((div_phi, div_theta, 3))
	outer = np.empty_like(inner)
	for i, j in np.ndindex(div_phi, div_theta):
		point, normal = lcfs.point_normal(math.tau * i / div_phi, math.tau * j / div_theta, 1.0, False)
		inner[i, j], outer[i, j] = point, np.add(point, np.multiply(normal, thickness))
	return Geometry.bspline_geometry(outer).boolean_subtract(Geometry.bspline_geometry(inner)), outer


def materials(ncoils: int) -> tuple[openmc.Material, list[openmc.Material]]:
	"""PbLi 増殖材と、巻線パックを均質化したコイル材をコイル本数ぶん。名前が DAGMC のタグと結線する。

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
	pack = openmc.Material.mix_materials([steel, copper, nb3sn, epoxy], [0.50, 0.25, 0.15, 0.10], "vo")

	# コイル別のタリーを引けるよう、同一組成をタグごとに複製する
	coils = []
	for i in range(ncoils):
		coil = pack.clone()
		coil.name = f"coil{i:02d}"
		coils.append(coil)
	return pbli, coils


def fusion_power(samples: np.ndarray, volume_elements: np.ndarray) -> dict[str, float]:
	"""VMEC 平衡から核融合出力を積分する。返す体積は VMEC の volume_p との突き合わせ検証用。

	al_07 の reaction_rate は相対重み n²⟨σv⟩ (⟨σv⟩ は cm³/s) なので、
	絶対値には n_D = n_T = n/2 の (1/2)² と cm³ → m³ の 1e-6 を掛ける。
	"""
	cube = math.tau * math.tau  # (φ, θ, s) の一様サンプルが張る座標体積
	rate = float((0.25e-6 * reaction_rate(samples[:, 2]) * volume_elements).mean() * cube)
	return {"volume": float(volume_elements.mean() * cube), "rate": rate, "power": rate * DT_ENERGY * JOULE_PER_EV}


def heating(
	h5m: pathlib.Path,  # DAGMC 幾何。material タグ pbli / coil00.. が材料名と結線する
	work: pathlib.Path,  # OpenMC の作業ディレクトリ
	source: list[openmc.IndependentSource],
	mesh: openmc.RegularMesh,
	pbli: openmc.Material,
	coils: list[openmc.Material],
	particles: int,
	batches: int,
) -> dict[str, Any]:
	"""コイルの核発熱と高速中性子束を OpenMC で出す。

	FENDL-3.2 は MT=901 を持たないので heating-local は警告もなくゼロになる。heating と
	photon_transport の組み合わせが唯一の正しい選択である。
	"""
	openmc.reset_auto_ids()
	total = openmc.Tally(name="coil")
	total.filters = [openmc.MaterialFilter(coils)]
	total.scores = ["heating"]
	mapped = openmc.Tally(name="map")
	mapped.filters = [openmc.MeshFilter(mesh), openmc.MaterialFilter(coils)]
	mapped.scores = ["heating"]
	fast = openmc.Tally(name="fast")
	fast.filters = [openmc.MaterialFilter(coils), openmc.EnergyFilter([FAST, 20e6])]
	fast.scores = ["flux"]

	settings = openmc.Settings(run_mode="fixed source", source=source, particles=particles, batches=batches)
	settings.photon_transport = True
	model = openmc.Model(
		geometry=openmc.Geometry(openmc.DAGMCUniverse(str(h5m)).bounded_universe()),
		materials=openmc.Materials([pbli, *coils]),
		settings=settings,
		tallies=openmc.Tallies([total, mapped, fast]),
	)
	work.mkdir(parents=True, exist_ok=True)
	with openmc.StatePoint(model.run(cwd=work, output=False)) as statepoint:
		one = statepoint.get_tally(name="coil")
		grid = statepoint.get_tally(name="map").summation(filter_type=openmc.MaterialFilter, remove_filter=True)
		flux = statepoint.get_tally(name="fast")
		return {
			"heating": one.mean.ravel(),  # コイル別 [eV / 線源中性子]。並びは coils と同じ
			"error": one.std_dev.ravel(),
			# メッシュフィルタのビンは x が最内で回るので order="F" でないと軸が入れ替わる
			"map": grid.mean.reshape(mesh.dimension, order="F"),
			"flux": flux.mean.ravel(),  # コイル別 [cm / 線源中性子]。体積で割ると n/cm^2
			"transport": float(statepoint.runtime["transport"]),
		}


TEMPLATE = """# モジュラーコイルの核発熱 (al_09)

al_06 は「PbLi 殻を厚くするほど TBR が上がる」と示し、al_08 は「厚みを置ける空間はコイルが決める」と
示した。その反対側、つまり**コイルが浴びる側**の制約をここで数値にする。超伝導コイルの成立性は
核発熱密度と高速中性子フルエンスで決まり、どちらもこの計算でしか出ない。

**遮蔽体は入れていない。** 増殖材 {thickness} cm とその外の真空だけである。遮蔽が要るかどうかではなく、
どれだけ要るかを決めるための下限値としてこの構成を選んだ。

配位は ParaStell 同梱の `examples/wout_vmec.nc` をそのまま使う。nfp=4 の準ヘリカル配位で
R=11.08 m、a=1.70 m、⟨B⟩=5.87 T、β=5.1%。simsopt の
`wout_20220102-01-053-003_QH_nfp4_aspect6p5_beta0p05_iteratedWithSfincs_reference.nc` と
4 桁一致する同じ配位で、al_03 以降のスクリプトはすべてこれを読む。

## 方法

### 幾何

コイルは al_08 の stage-2 最適化をそのまま import して起こす。独立コイル {ncoils} 本、対称像込みで
{ncoil_total} 本。コイル-プラズマ距離は要求 {standoff} m に対し {achieved} m まで寄り、巻線パック
半厚と増殖材 {thickness} cm を引いた隙間は {clearance} m でコイルと増殖材は干渉しない。

断面は {width} × {height} cm の矩形 (parastell の config.yaml と同じ)。掃引は al_08 の
guided spines を使う: コイル各点を nearest 射影で LCFS に落とし、その法線方向へずらした
guide 曲線が断面の捻りを点ごとに制御する (cadrum の Auxiliary、断面は常に接線と直交)。
旧 al_10 ドラフトは断面の向きを 1 本の固定ベクトルで運んだため断面が最大 84 度寝て
DAGMC が粒子をロストしたが、この方式で解消した。掃引体積は断面積 × 中心線長に対し
{volume_error_min}〜{volume_error_max} % で、既知の掃引面近似誤差の範囲にある。

増殖材は LCFS を面内法線方向へ {thickness} cm 押し出した PbLi 殻 (al_06 / al_07 と同じ作り方) である。

### 核融合出力

タリーは線源中性子 1 個あたりで出るので、W に直すには線源率が要る。固定値を置かず、
VMEC 平衡から積分した。

$$
S = \\int (n/2)^2 \\langle\\sigma v\\rangle \\sqrt g \\; d\\phi \\, d\\theta \\, ds
$$

反応率プロファイルとヤコビアン $\\sqrt g$ は al_07 の `reaction_rate` / `jacobian` をそのまま使う。
同じ積分でプラズマ体積が **{volume_mc} m³** と出る。VMEC 自身の `volume_p` が 635.7 m³ なので、
ヤコビアンと積分が正しいことの検証になっている。得られる出力は **{power} GW**、
線源率 {rate} n/s である。

### 中性子輸送

線源は al_07 の case_2 (一様サンプル {nsample} 点の強度を反応率 × 体積要素にした重み付き点線源)。
{particles} 粒子 × {batches} バッチ。

**`heating` と光子輸送の組み合わせは選択ではなく必然である。** この計算に使う FENDL-3.2 は
192 核種すべてに MT=301 (`heating`) を持つが、**MT=901 (`heating-local`) は 1 核種も持たない**。
`heating-local` を指定すると警告もエラーも出ずにゼロが返る。そして `heating` は二次 γ の
エネルギーを局所に落とさないので、`photon_transport = true` が無ければ捕獲 γ の寄与が丸ごと消える。

コイル材は巻線パックを体積分率で均質化した (**比率は仮定**): SS316 50%、Cu 25%、Nb₃Sn 15%、
エポキシ 10%。DAGMC の material タグをコイルごとに分けたので、発熱とフルエンスはコイル別に出る。

## 結果

![コイル材に落ちた核発熱密度のボクセル別 3D 散布図 (対数色)。ボクセルにはコイル外の空間も含まれるため、値は材料の局所密度より薄まる。プラズマに面した内側ミッドプレーンで最も高い。]({out_heating_png})

![コイル別の体積平均発熱密度 (対数目盛)。点線は DEMO TF コイルのピーク目標 {heating_limit} W/m³ で、実測の 3 桁下にある。]({out_percoil_png})

![増殖材 {thickness} cm と {ncoil_total} 本のコイル導体。左上 ISO、右上 +Z、左下 +X、右下 +Y。]({out_geometry_png})

| 量 | 値 |
|:--|--:|
| 核融合出力 (VMEC から積分) | {power} GW |
| 線源率 | {rate} n/s |
| コイル体積 (全 {ncoil_total} 本) | {coil_volume} m³ |
| コイル核発熱 合計 | {watts} MW |
| コイル別平均発熱密度 | {cold_density}〜{hot_density} W/m³ (最大: コイル {hot_coil}) |
| 3D ボクセルのピーク | {peak_density} W/m³ |
| DEMO TFC 目標 | {heating_limit} W/m³ |
| 高速中性子フルエンス (最悪コイル) | {fluence} n/m² / フル出力年 |
| Nb₃Sn 目標 | {fluence_limit} n/m² |
| コイルタリーの相対誤差 | {relative_error} % |
| 輸送の計算時間 (wall-clock) | {transport} s |

## 考察

### 遮蔽なしでは桁が足りない

ピーク核発熱密度は **{peak_density} W/m³** で、DEMO TF コイルの目標 {heating_limit} W/m³ の
**約 {peak_ratio} 倍**である。高速中性子フルエンスは最悪コイルで {fluence} n/m² / フル出力年で、
Nb₃Sn の許容 {fluence_limit} n/m² に **{fluence_days} 日**で到達する。

これは失敗ではなく、この構成が答えるべき問いへの答えである。増殖材 {thickness} cm だけでは
超伝導コイルは成立しない。

### 必要な遮蔽厚

14 MeV 中性子に対する遮蔽材の減衰長は 7〜10 cm である。ピークを {heating_limit} W/m³ まで
落とすには $\ln$({peak_density}/{heating_limit}) ≈ {attenuation} cm 相当の追加減衰が要る。
parastell の例が遮蔽 50 cm を置いているのと矛盾しない。

ただしこれは指数減衰だけを見た概算で、実際には γ のビルドアップと、増殖材を薄くすることによる
TBR の低下がトレードオフに入る。al_06 の TBR-厚み曲線と本計算を同じ半径方向予算の上で解くのが
次段である。

### コイル間の差

material タグをコイルごとに分けたので、旧ドラフトで出せなかった「どのコイルが最も熱いか」が出る。
体積平均発熱密度は {cold_density}〜{hot_density} W/m³ に分布し、最大はコイル {hot_coil} である。
対称像 (2·nfp = 8 像) は統計誤差の範囲で同じ値になるはずで、そこからの逸脱は線源サンプリングの偏りの指標になる。

### この計算が答えていないこと

- **ピーク値の統計**。合計は相対誤差 {relative_error} % で決まるが、3D マップのボクセルごとは
  それより粗い。ピーク {peak_density} W/m³ は桁を示す値であって有効数字ではない。
- **均質化の妥当性**。実際の巻線パックは層構造を持ち、Cu 安定化材と超伝導線で発熱密度が違う。
  局所のホットスポットは均質化では出ない。
- **掃引体積の {volume_error_min}〜{volume_error_max} %**。OCCT の掃引面近似による系統誤差で、
  発熱の読みに同程度のバイアスを与えうる。
"""


if __name__ == "__main__":
	main()
