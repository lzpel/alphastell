#!/usr/bin/env -S MSYS_NO_PATHCONV=1 docker run --rm -i -e OPENMC_CROSS_SECTIONS -e PATH=/opt/conda/envs/parastell_env/bin:/usr/bin:/bin -v ${PWD}:/work -w /work ghcr.io/svalinn/parastell-ci /opt/conda/envs/parastell_env/bin/python
import json
import pathlib
from typing import Any

import numpy as np
import openmc


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	coils: pathlib.Path = pathlib.Path("/opt/parastell/examples/coils.example"),  # parastell-ci コンテナ同梱
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".json").name,
) -> dict[str, Any]:
	"""ParaStell で層ごとの STEP と四面体線源メッシュを書く。輸送計算とレポートは al_101 に任せる。"""
	parameters = geometry_parameters()
	out.parent.mkdir(parents=True, exist_ok=True)
	volumes, source = build(wout, coils, out, parameters)
	for name, volume in volumes.items():
		print(f"{name:14s} {volume:8.3f} m3/sector")
	print(f"source: {source['n_tets']} tets, {source['rate']:.3e} n/s per sector, plasma {source['plasma_volume']:.1f} m3/sector")
	fields = {"parameters": parameters, "volumes": volumes, "source": source}
	out.write_text(json.dumps(fields, indent=1, ensure_ascii=False), encoding="utf-8")
	print(f"{out}: {out.stat().st_size} bytes")
	return fields


def geometry_parameters() -> dict[str, Any]:
	"""radial build とマグネットの寸法 [cm]。parastell の examples/parastell_cad_to_dagmc_example.py と同じ値。

	al_10x はこれを import してレポートに使う。
	"""
	return {
		"wall_s": 1.08,  # 第一壁内面の規格化磁束面ラベル。LCFS の少し外
		"first_wall": 5.0,
		"back_wall": 5.0,
		"shield": 50.0,
		"vacuum_vessel": 10.0,
		"breeder": [  # 9 (トロイダル 0..90°) × 9 (ポロイダル 0..360°) の厚さ行列。コイルに近い場所で薄い
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
		"magnet_width": 40.0,
		"magnet_thickness": 50.0,
		"sample_mod": 6,  # コイルフィラメントの点を何点おきに掃引に使うか
		"source_cfs": 11,  # 線源メッシュの格子点数: 規格化磁束 s (0..1)
		"source_theta": 61,  # ポロイダル角 (0..360°)
		"source_phi": 61,  # トロイダル角 (0..90°)
	}


def build(wout: pathlib.Path, coils: pathlib.Path, out: pathlib.Path, parameters: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
	"""parastell で 1 周期分の in-vessel build・マグネット・四面体線源メッシュを作る。

	層ごとの STEP を out.<層>.step、線源メッシュを out.source.h5m、tet ごとの強度 [n/s] を out.source.npy に書く。
	戻り値は層名 → 体積 [m³/扇形] (chamber は s≤wall_s の void) と、線源の要約。
	"""
	import cadquery as cq  # コンテナにしか無いので関数内で import し、al_10x がこのモジュールを import できるようにする
	import parastell.parastell as ps

	stellarator = ps.Stellarator(str(wout))
	toroidal_angles = np.linspace(0.0, 90.0, 9)
	poloidal_angles = np.linspace(0.0, 360.0, 9)
	uniform = np.ones((len(toroidal_angles), len(poloidal_angles)))
	radial_build = {
		"first_wall": {"thickness_matrix": uniform * parameters["first_wall"]},
		"breeder": {"thickness_matrix": np.array(parameters["breeder"])},
		"back_wall": {"thickness_matrix": uniform * parameters["back_wall"]},
		"shield": {"thickness_matrix": uniform * parameters["shield"]},
		"vacuum_vessel": {"thickness_matrix": uniform * parameters["vacuum_vessel"]},
	}
	stellarator.construct_invessel_build(toroidal_angles, poloidal_angles, parameters["wall_s"], radial_build)
	stellarator.construct_magnets_from_filaments(
		str(coils), parameters["magnet_width"], parameters["magnet_thickness"], 90.0, sample_mod=parameters["sample_mod"]
	)

	volumes = {}
	for name, solid in stellarator.invessel_build.Components.items():
		solid.exportStep(str(out.with_suffix(f".{name}.step")))
		volumes[name] = solid.Volume() * 1e-6
	magnets = cq.Compound.makeCompound(stellarator.magnet_set.all_coil_solids)
	magnets.exportStep(str(out.with_suffix(".magnets.step")))
	volumes["magnets"] = magnets.Volume() * 1e-6

	# 線源: parastell 既定の n(s), T(s) で tet ごとの反応率を積分した強度 [n/s]。al_101 は h5m と npy を読むだけ
	stellarator.construct_source_mesh(
		np.linspace(0.0, 1.0, parameters["source_cfs"]),
		np.linspace(0.0, 360.0, parameters["source_theta"]),
		np.linspace(0.0, 90.0, parameters["source_phi"]),
	)
	stellarator.export_source_mesh(filename="source_mesh", export_dir=str(out.parent))  # parastell は filename の拡張子を .h5m に差し替える
	(out.parent / "source_mesh.h5m").replace(out.with_suffix(".source.h5m"))
	strengths = np.asarray(stellarator.source_mesh.strengths, dtype=float)
	np.save(out.with_suffix(".source.npy"), strengths)
	source = {
		"h5m": out.with_suffix(".source.h5m").name,
		"strengths": out.with_suffix(".source.npy").name,
		"n_tets": int(strengths.size),
		"rate": float(strengths.sum()),  # 扇形 1 つ分の中性子発生率 [n/s]
		"plasma_volume": float(np.sum(stellarator.source_mesh.volumes)) * 1e-6,  # tet の体積和 [m³/扇形]
	}
	return volumes, source


def materials() -> list[openmc.Material]:
	"""ParaStell 論文 Table 1/2 (ARIES-CS の DCLL) の均質化材料。name が DAGMC の材料タグと一致する。al_10x が import して使う。"""

	def constituent_material(name: str, density: float, atoms: dict[str, float], percent: str = "ao", enrichment_isotopes: dict[str, float] | None = None) -> openmc.Material:
		"""enrichment_isotopes は {"Li6": 90.0} のように同位体名 → 存在比 (percent と同じ単位)。"""
		material = openmc.Material(name=name)
		for element, fraction in atoms.items():
			target = next((k for k in enrichment_isotopes or {} if k.rstrip("0123456789") == element), None)
			material.add_element(element, fraction, percent, **{"enrichment": enrichment_isotopes[target], "enrichment_target": target, "enrichment_type": percent} if target else {})
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
		mix([rafm, water], [0.51, 0.49], "vo", name="vacuum_vessel"),
		mix([rafm, copper, nb3sn, helium, insulator], [0.674, 0.193, 0.051, 0.042, 0.04], "vo", name="magnets"),
	]


if __name__ == "__main__":
	main()
