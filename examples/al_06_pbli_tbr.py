#!/usr/bin/env python3
"""LCFS を法線方向に押し出した PbLi 殻の TBR を OpenMC で出す (al_06)。

構造材も遮蔽も冷却材も無い純 PbLi なので、ここで出る値がこの配位の TBR 上限になる。
al_07 以降で不均質な WCLL 構造を入れて、どこまで下がるかを見るための基準点。

s>1 の Fourier 外挿は s=1.08 でも 2〜17 cm しか稼げず、s を上げると発散するので、
厚みは磁気面の法線方向オフセットで作る (この配位では 70 cm まで自己交差しない)。

    make al-06
"""

import math
import pathlib

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openmc
import typst
from cad_to_dagmc import CadToDagmc

from alphastell import SurfaceRZFourier, Geometry

WOUT = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc"
OUT = pathlib.Path("out")
WORK = OUT / "al_06_openmc"

DIV_PHI, DIV_THETA = 96, 40  # 制御点。中性子の平均自由行程は PbLi で約 7 cm なのでこれで足りる
THICKNESS = [0.3, 0.5, 0.7]  # m
SOURCES, PARTICLES, BATCHES = 200, 40000, 10

with open(WOUT, "rb") as f:
	surface = SurfaceRZFourier.load(f)


def offset_grid(thickness):
	"""LCFS の点と、それを面内法線方向に thickness だけ押した点を (φ, θ) 格子で返す。"""
	inner = np.empty((DIV_PHI, DIV_THETA, 3))
	outer = np.empty_like(inner)
	for i, j in np.ndindex(DIV_PHI, DIV_THETA):
		point, normal = surface.point_normal(math.tau * i / DIV_PHI, math.tau * j / DIV_THETA, 1.0, False)
		inner[i, j], outer[i, j] = point, np.add(point, np.multiply(normal, thickness))
	return inner, outer


def shell_solid(inner, outer):
	steps = []
	for name, points in (("inner", inner), ("outer", outer)):
		path = OUT / f"al_06_{name}.step"
		with open(path, "wb") as f:
			Geometry.bspline_geometry(points).write_step(f)
		steps.append(cq.importers.importStep(str(path)))
	return steps[1].cut(steps[0])


def tbr(shell):
	"""CAD → DAGMC → OpenMC。material_tags の文字列と Material.name の一致だけが両者の結線。"""
	h5m = str(OUT / "al_06.h5m")
	cad = CadToDagmc()
	cad.add_cadquery_object(shell, material_tags=["pbli"])
	cad.export_dagmc_h5m_file(filename=h5m, scale_factor=100)  # VMEC は m、OpenMC は cm

	pbli = openmc.Material(name="pbli")
	pbli.add_element("Li", 17.0, "ao", enrichment=90.0, enrichment_target="Li6", enrichment_type="ao")
	pbli.add_element("Pb", 83.0, "ao")
	pbli.set_density("g/cm3", 9.4)

	# プラズマ内部に点線源を散らす。厚い殻が全周を覆うので TBR は線源分布にほぼ依存しない。
	# タリーは合計 strength でスケールされるので、合計が 1 になるよう分けておく。
	rng = np.random.default_rng(0)
	source = [
		openmc.IndependentSource(
			space=openmc.stats.Point(np.multiply(surface.point_normal(phi, theta, s, False)[0], 100)),
			energy=openmc.stats.Discrete([14.07e6], [1.0]),
			strength=1.0 / SOURCES,
		)
		for phi, theta, s in rng.random((SOURCES, 3)) * [math.tau, math.tau, 1.0]
	]
	tally = openmc.Tally(name="tbr")
	tally.scores = ["(n,Xt)"]

	# implicit_complement を指定していないので殻の内外は真空。bounded_universe が外側に真空境界を張る。
	model = openmc.Model(
		geometry=openmc.Geometry(openmc.DAGMCUniverse(h5m).bounded_universe()),
		materials=openmc.Materials([pbli]),
		settings=openmc.Settings(run_mode="fixed source", source=source, particles=PARTICLES, batches=BATCHES),
		tallies=openmc.Tallies([tally]),
	)
	WORK.mkdir(parents=True, exist_ok=True)
	with openmc.StatePoint(model.run(cwd=WORK, output=False)) as statepoint:
		result = statepoint.get_tally(name="tbr")
		return float(result.mean.flat[0]), float(result.std_dev.flat[0])


OUT.mkdir(parents=True, exist_ok=True)
results = []
for thickness in THICKNESS:
	inner, outer = offset_grid(thickness)
	value, error = tbr(shell_solid(inner, outer))
	results.append((thickness, value, error))
	print(f"{thickness * 100:.0f} cm: TBR = {value:.3f} +/- {error:.3f}")

# --- 図 -------------------------------------------------------------------
# 断面は最後に作った格子 (最大厚み) の φ=0 を使う
figure, axes = plt.subplots(figsize=(5.5, 5.5))
for grid, style in ((inner, "-"), (outer, "--")):
	loop = np.concatenate([grid[0], grid[0][:1]])
	axes.plot(np.hypot(loop[:, 0], loop[:, 1]), loop[:, 2], style, color="#2b2b2b", linewidth=1.2)
axes.set(xlabel="R [m]", ylabel="Z [m]", aspect="equal", title=f"phi=0 section: LCFS and +{THICKNESS[-1] * 100:.0f} cm normal offset")
figure.savefig(OUT / "al_06_section.png", dpi=150, bbox_inches="tight")
plt.close(figure)

figure, axes = plt.subplots(figsize=(6.0, 4.0))
axes.errorbar([t * 100 for t, _, _ in results], [v for _, v, _ in results], [e for _, _, e in results], marker="o", label="stellarator shell")
# 球殻 (内半径 200 cm の真空 + PbLi) の参照値。形状の違いだけを見るための対照。
axes.plot([30, 50, 70, 100], [0.631, 1.188, 1.515, 1.724], "--", marker="x", color="#888888", label="sphere shell (reference)")
axes.axhline(1.1, color="#c0392b", linewidth=0.9)
axes.set(xlabel="PbLi thickness [cm]", ylabel="TBR", title="TBR vs breeder thickness (Li-6 90%, no structure)")
axes.legend()
axes.grid(alpha=0.3)
figure.savefig(OUT / "al_06_tbr.png", dpi=150, bbox_inches="tight")
plt.close(figure)

# --- PDF レポート ---------------------------------------------------------
rows = "".join(f"  [{t * 100:.0f}], [{v:.3f}], [{e:.3f}],\n" for t, v, e in results)
report = f"""#set page(paper: "a4", margin: 2cm, numbering: "1")
#set text(font: ("Yu Gothic", "Meiryo", "Noto Sans CJK JP"), size: 10pt, lang: "ja")
#set par(justify: true)

= 純 PbLi 殻の TBR (al_06)

VMEC 平衡 `wout_vmec.nc` (nfp=4, R≈11 m) の LCFS を法線方向にオフセットして PbLi 殻を作り、
OpenMC で TBR を計算した。構造材・冷却材・遮蔽を含まないので、この配位で到達しうる TBR の
上限にあたる。

== 方法

厚みは s>1 の Fourier 外挿ではなく面内法線のオフセットで作った。s=1.08 では 2〜17 cm しか
稼げず、s を上げると外挿が発散して同じ s でも場所により 5 cm と 138 cm が混在するためである。
法線オフセットはこの配位では 70 cm まで断面の自己交差を起こさない。

CAD は Rust/cadrum が B スプライン曲面から内外 2 個のソリッドを作り、CadQuery で差を取って
殻にした。`cad_to_dagmc` が DAGMC 形式に変換し、`material_tags` の文字列 `pbli` が
`openmc.Material` の名前と一致することで材料が結線される。VMEC は m、OpenMC は cm なので
書き出し時に 100 倍している。

線源はプラズマ内部に散らした {SOURCES} 個の 14.07 MeV 点線源、{PARTICLES} 粒子 × {BATCHES} バッチ。
増殖材は Li#sub[17]Pb#sub[83] (⁶Li 90% 濃縮、9.4 g/cm³)。

== 結果

#table(
  columns: 3,
  align: (right, right, right),
  [厚み [cm]], [TBR], [誤差],
{rows})

#figure(image("al_06_tbr.png", width: 88%), caption: [厚みに対する TBR。破線は内半径 200 cm の
球殻による参照値で、形状の違いだけを取り出すための対照。赤線は要求 TBR の目安 1.1。])

#figure(image("al_06_section.png", width: 62%), caption: [φ=0 断面。実線が LCFS、破線が
法線方向オフセット面。])

== 考察

純 PbLi でも 50 cm 程度では要求 TBR の余裕が乏しく、飽和は遅い。ここに第一壁・二重管・
補強板・背面支持構造・遮蔽が入ると TBR は単調に下がるので、al_07 以降で不均質な WCLL 構造を
入れたときにどこまで落ちるかが本題になる。Stellaris の公表値 1.07 の厳しさもこの傾きから読める。
"""
(OUT / "al_06_report.typ").write_text(report, encoding="utf-8")
typst.compile(OUT / "al_06_report.typ", output=OUT / "al_06_report.pdf")
print(f"{OUT / 'al_06_report.pdf'}: {(OUT / 'al_06_report.pdf').stat().st_size} bytes")
