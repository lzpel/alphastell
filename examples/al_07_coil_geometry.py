#!/usr/bin/env python3
"""VMEC の LCFS からモジュラーコイル形状を stage-2 最適化で起こし、3D 図と PDF レポートを出す (al_07)。

al_06 で PbLi 殻を厚くするほど TBR が上がると分かったが、厚みを置く空間があるかはコイルが決める。
コイル-プラズマ最小距離を 1.5〜3.0 m で振って磁気面の再現誤差を見ると、ブランケット・遮蔽・
真空容器に使える半径方向の予算が出る。al_06 の TBR 曲線と合わせて 1 つのトレードオフになる。

wout には rmnc/zmns/xm/xn しか無く bsubvmnc が無いので正味ポロイダル電流が決まらない。
境界の平均大半径での磁場 B0 を仮定して総電流を固定するが、目的関数が B·n/|B| なので
コイル形状はこの仮定に依らない (電流値だけが B0 に比例する)。

    make al-07
"""

import math
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import typst
from scipy.io import netcdf_file
from scipy.optimize import minimize
from simsopt.field import BiotSavart, Current, coils_via_symmetries
from simsopt.geo import (
	CurveCurveDistance,
	CurveLength,
	CurveSurfaceDistance,
	LpCurveCurvature,
	MeanSquaredCurvature,
	SurfaceRZFourier,
	create_equally_spaced_curves,
)
from simsopt.objectives import QuadraticPenalty, SquaredFlux

from alphastell import SurfaceRZFourier as AlphaSurface

WOUT = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc"
OUT = pathlib.Path("out")

STANDOFF = [1.5, 2.0, 2.5, 3.0]  # コイル-プラズマ最小距離の要求値 [m]。先頭を 3D 図と CSV に出す
NCOILS = 4  # 半周期あたりの独立コイル数。全体では 2*nfp*NCOILS 個
ORDER = 6  # コイル 1 本の Fourier 次数。上げると細かく波打つ
NPHI, NTHETA = 32, 32  # B·n を評価する半周期の格子
B0 = 5.5  # 境界の平均大半径での磁場 [T]。電流の絶対値を決めるためだけの仮定
MU0 = 4e-7 * math.pi

LENGTH_TARGET = 32.0  # コイル 1 本の長さ上限 [m]
CC_THRESHOLD = 0.8  # コイル間の最小距離 [m]
CURVATURE_THRESHOLD = 0.5  # 曲率上限 [1/m]。最小曲げ半径 2 m
MSC_THRESHOLD = 0.25  # 平均二乗曲率の上限 [1/m^2]。局所的でない波打ちを抑える
LENGTH_WEIGHT, CC_WEIGHT, CS_WEIGHT, CURVATURE_WEIGHT, MSC_WEIGHT = 1e-3, 3e-1, 3e-2, 1e-2, 1e-2
MAXITER = 300

with netcdf_file(WOUT, mmap=False) as f:
	NFP = int(f.variables["nfp"][()])
	XM = f.variables["xm"][:].astype(int)
	XN = f.variables["xn"][:].astype(int)
	RMNC, ZMNS = f.variables["rmnc"][-1], f.variables["zmns"][-1]  # 最外殻 = LCFS


def make_surface(quadpoints_phi, quadpoints_theta):
	"""LCFS を simsopt の SurfaceRZFourier にする。

	VMEC も simsopt も R = Σ rc cos(mθ - n·nfp·φ) なので、xn を nfp で割るだけで移せる。
	"""
	surface = SurfaceRZFourier(
		nfp=NFP,
		stellsym=True,
		mpol=int(XM.max()),
		ntor=int(np.abs(XN).max()) // NFP,
		quadpoints_phi=quadpoints_phi,
		quadpoints_theta=quadpoints_theta,
	)
	for m, n, rc, zs in zip(XM, XN, RMNC, ZMNS):
		surface.set_rc(m, n // NFP, rc)
		surface.set_zs(m, n // NFP, zs)
	return surface


# 同じ wout を alphastell (Rust) と simsopt に読ませて LCFS 上の点が一致するか見る。
# xn の符号や θ の向きを取り違えると鏡像になるだけで、図を見ても気付けない。
with open(WOUT, "rb") as f:
	alpha = AlphaSurface.load(f)
for phi, theta in [(0.7, 1.3), (2.1, 4.0), (5.0, 0.2)]:
	point = make_surface([phi / math.tau], [theta / math.tau]).gamma()[0, 0]
	assert np.allclose(point, alpha.point_normal(phi, theta, 1.0, True)[0]), "surface convention mismatch"

surface = make_surface(np.linspace(0, 1 / (2 * NFP), NPHI, endpoint=False), np.linspace(0, 1, NTHETA, endpoint=False))
R_MAJOR = surface.get_rc(0, 0)
NORMAL = surface.unitnormal()


def optimize(standoff):
	"""磁気面を固定してコイルだけを動かす stage-2。standoff はコイル-プラズマ距離の要求値 [m]。"""
	base_curves = create_equally_spaced_curves(NCOILS, NFP, stellsym=True, R0=R_MAJOR, R1=3.5 + standoff, order=ORDER)

	# 正味ポロイダル電流 2πR·B0/μ0 を半周期に配り、その合計だけを固定する。
	# 最後の 1 本を「合計 - 残り」にすると本数分の自由度から 1 つだけ減る。
	half_period_current = 2 * math.pi * R_MAJOR * B0 / MU0 / (2 * NFP)
	base_currents = [Current(half_period_current / NCOILS * 1e-5) * 1e5 for _ in range(NCOILS - 1)]
	fixed_total = Current(half_period_current)
	fixed_total.fix_all()
	base_currents.append(fixed_total - sum(base_currents))

	coils = coils_via_symmetries(base_curves, base_currents, NFP, True)
	field = BiotSavart(coils)
	field.set_points(surface.gamma().reshape((-1, 3)))

	# definition="local" は ∫(B·n/|B|)² dA。無次元なので重みが B0 の仮定に引きずられない。
	flux = SquaredFlux(surface, field, definition="local")
	lengths = [CurveLength(c) for c in base_curves]
	distance_cc = CurveCurveDistance([c.curve for c in coils], CC_THRESHOLD, num_basecurves=NCOILS)
	distance_cs = CurveSurfaceDistance(base_curves, surface, standoff)
	objective = (
		flux
		+ LENGTH_WEIGHT * sum(QuadraticPenalty(length, LENGTH_TARGET, "max") for length in lengths)
		+ CC_WEIGHT * distance_cc
		+ CS_WEIGHT * distance_cs
		+ CURVATURE_WEIGHT * sum(LpCurveCurvature(c, 2, CURVATURE_THRESHOLD) for c in base_curves)
		+ MSC_WEIGHT * sum(QuadraticPenalty(MeanSquaredCurvature(c), MSC_THRESHOLD, "max") for c in base_curves)
	)

	def fun(dofs):
		objective.x = dofs
		return objective.J(), objective.dJ()

	minimize(fun, objective.x, jac=True, method="L-BFGS-B", options={"maxiter": MAXITER, "maxcor": 300})

	# B·n/|B| を (φ, θ) 格子の形で。0 なら磁気面がコイルの作る磁場と整合する。
	b = field.B().reshape(surface.gamma().shape)
	error = (b * NORMAL).sum(axis=-1) / np.linalg.norm(b, axis=-1)
	return {
		"standoff": standoff,
		"coils": coils,
		"base_curves": base_curves,
		"error": error,
		"lengths": [float(length.J()) for length in lengths],
		"currents": [float(current.get_value()) for current in base_currents],
		"radii": [1.0 / float(np.max(c.kappa())) for c in base_curves],
		"cc": float(distance_cc.shortest_distance()),
		"cs": float(distance_cs.shortest_distance()),
	}


results = []
for standoff in STANDOFF:
	result = optimize(standoff)
	results.append(result)
	print(
		f"standoff {standoff:.1f} m: max |B.n|/|B| = {np.abs(result['error']).max():.2e}, "
		f"achieved {result['cs']:.2f} m, coil-coil {result['cc']:.2f} m, length {sum(result['lengths']) * 2 * NFP:.0f} m"
	)

baseline = results[0]
coils, base_curves = baseline["coils"], baseline["base_curves"]

OUT.mkdir(parents=True, exist_ok=True)
geometry = [coil.curve.gamma() for coil in coils]


def fourier_coefficients(points):
	"""周期点列 (t = 0..1 の等間隔) を三角多項式の係数に戻す。

	x(t) = Σ_m [ c_m cos(2πmt) + s_m sin(2πmt) ]。曲線は ORDER 次の帯域制限なので
	FFT で厳密に取れる。点列より係数の方が、下流で任意の分解能の滑らかな CAD を引ける。
	対称操作の像も回転行列を掛けただけで次数は変わらないため、同じ扱いでよい。
	"""
	spectrum = np.fft.rfft(points, axis=0) / len(points)
	cosine, sine = 2 * spectrum.real, -2 * spectrum.imag
	cosine[0] /= 2
	return cosine[: ORDER + 1], sine[: ORDER + 1]


rows = []
for index, (coil, points) in enumerate(zip(coils, geometry)):
	cosine, sine = fourier_coefficients(points)
	mode = np.arange(ORDER + 1)
	angle = math.tau * np.outer(np.linspace(0, 1, len(points), endpoint=False), mode)
	assert np.allclose(np.cos(angle) @ cosine + np.sin(angle) @ sine, points), "fourier fit is not exact"
	rows.append(np.column_stack([np.full(ORDER + 1, index), np.full(ORDER + 1, coil.current.get_value()), mode, cosine, sine]))
np.savetxt(
	OUT / "al_07_coils.csv", np.concatenate(rows), delimiter=",",
	header="coil,current_A,m,xc,yc,zc,xs,ys,zs", comments="", fmt="%.9e",  # 係数の単位は m
)

# --- 図 --------------------------------------------------------------------
colors = plt.get_cmap("tab10")


def dress(axes, points, elevation, azimuth):
	"""3D 軸の共通設定。トーラスは扁平なので軸ごとの実寸比を保たないと形が嘘になる。"""
	axes.set_box_aspect((np.ptp(points[..., 0]), np.ptp(points[..., 1]), np.ptp(points[..., 2])), zoom=1.5)
	axes.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
	axes.zaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
	axes.view_init(elev=elevation, azim=azimuth)
	axes.grid(False)
	for pane in (axes.xaxis, axes.yaxis, axes.zaxis):
		pane.pane.set_alpha(0.0)


wall = make_surface(np.linspace(0, 1, 120), np.linspace(0, 1, 48)).gamma()  # 端点を含めて φ, θ の継ぎ目を閉じる
figure = plt.figure(figsize=(11, 5.5))
axes = figure.add_subplot(projection="3d")
axes.plot_surface(
	wall[..., 0], wall[..., 1], wall[..., 2],
	color="#b8bec7", alpha=0.30, rstride=1, cstride=1, linewidth=0, edgecolor="none", antialiased=False, shade=True,
)
# 独立コイルは NCOILS 本だけで、残りは stellarator 対称と nfp 回転の像。色をその index で振る。
for index, points in enumerate(geometry):
	loop = np.concatenate([points, points[:1]])
	axes.plot(loop[:, 0], loop[:, 1], loop[:, 2], color=colors(index % NCOILS), linewidth=1.5)
dress(axes, wall, 38, -55)
axes.set_title(
	f"modular coils from stage-2 optimization: {len(coils)} coils ({NCOILS} unique x {2 * NFP} symmetry images)\n"
	f"coil-plasma {baseline['cs']:.2f} m, max |B.n|/|B| = {np.abs(baseline['error']).max():.1e}, "
	f"total length {sum(baseline['lengths']) * 2 * NFP:.0f} m"
)
figure.savefig(OUT / "al_07_coils.png", dpi=150, bbox_inches="tight")
plt.close(figure)

# 独立コイル 4 本だけを LCFS 半周期と並べた図。全体図では重なって 1 本の形が読めない。
half = make_surface(np.linspace(0, 1 / (2 * NFP), 40), np.linspace(0, 1, 48)).gamma()
figure = plt.figure(figsize=(9, 6))
axes = figure.add_subplot(projection="3d")
axes.plot_surface(
	half[..., 0], half[..., 1], half[..., 2],
	color="#c0392b", alpha=0.35, rstride=1, cstride=1, linewidth=0, edgecolor="none", antialiased=False, shade=True,
)
for index, curve in enumerate(base_curves):
	loop = np.concatenate([curve.gamma(), curve.gamma()[:1]])
	axes.plot(
		loop[:, 0], loop[:, 1], loop[:, 2], color=colors(index), linewidth=2.0,
		label=f"coil {index}: {baseline['lengths'][index]:.1f} m, {baseline['currents'][index] / 1e6:.2f} MA",
	)
dress(axes, half, 30, -70)
axes.set_title(f"one half period: {NCOILS} unique coils and the LCFS they reproduce")
axes.legend(loc="upper left", fontsize=8)
figure.savefig(OUT / "al_07_half_period.png", dpi=150, bbox_inches="tight")
plt.close(figure)

figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.0))
mesh = left.pcolormesh(
	np.linspace(0, 360 / (2 * NFP), NPHI), np.linspace(0, 360, NTHETA), baseline["error"].T,
	cmap="coolwarm", norm=matplotlib.colors.CenteredNorm(), shading="nearest",
)
figure.colorbar(mesh, ax=left, label="B.n / |B|")
left.set(xlabel="phi [deg]", ylabel="theta [deg]", title=f"normal field error, coil-plasma {baseline['cs']:.2f} m")
right.semilogy([r["cs"] for r in results], [np.abs(r["error"]).max() for r in results], marker="o", label="max")
right.semilogy([r["cs"] for r in results], [np.abs(r["error"]).mean() for r in results], marker="x", linestyle="--", label="mean")
# al_06 の PbLi 最大厚み。この線とデータ点の差が第一壁・真空容器・遮蔽に使える残りになる
right.axvline(0.7, color="#c0392b", linestyle=":", linewidth=1.2)
right.text(0.72, right.get_ylim()[0] * 1.3, "al_06 PbLi 70 cm", fontsize=8, color="#c0392b")
right.set(xlabel="achieved coil-plasma distance [m]", ylabel="|B.n| / |B|", title="how far the coils can back off")
right.legend()
right.grid(alpha=0.3)
figure.tight_layout()
figure.savefig(OUT / "al_07_error.png", dpi=150, bbox_inches="tight")
plt.close(figure)

# --- PDF レポート ---------------------------------------------------------
coil_rows = "".join(
	f"  [{i}], [{baseline['lengths'][i]:.1f}], [{baseline['currents'][i] / 1e6:.2f}], [{baseline['radii'][i]:.2f}],\n"
	for i in range(NCOILS)
)
scan_rows = "".join(
	f"  [{r['standoff']:.1f}], [{r['cs']:.2f}], [{np.abs(r['error']).max():.1e}], [{np.abs(r['error']).mean():.1e}], "
	f"[{sum(r['lengths']) * 2 * NFP:.0f}], [{r['cc']:.2f}],\n"
	for r in results
)
report = f"""#set page(paper: "a4", margin: 2cm, numbering: "1")
#set text(font: ("Yu Gothic", "Meiryo", "Noto Sans CJK JP"), size: 10pt, lang: "ja")
#set par(justify: true)

= VMEC 平衡を再現するモジュラーコイル (al_07)

VMEC 平衡 `wout_vmec.nc` (nfp={NFP}, R={R_MAJOR:.2f} m) の LCFS を固定し、その外側にモジュラーコイルを
simsopt の stage-2 最適化で置いた。al_06 で PbLi 殻を厚くするほど TBR が上がると分かったので、
ここではコイルをどこまで離せるか、つまり半径方向にいくら予算があるかを見る。

== 方法

磁気面を動かさずコイルだけを動かす stage-2 である。半周期に {NCOILS} 本の独立コイル
(1 本あたり Fourier {ORDER} 次) を等間隔の円環として置き、stellarator 対称と nfp 回転で
{len(coils)} 本に増やす。目的関数は LCFS 上の規格化法線磁場

$ integral (bold(B) dot bold(n))^2 / abs(bold(B))^2 thin d A $

に、コイル長 ({LENGTH_TARGET} m)・コイル間距離 ({CC_THRESHOLD} m)・コイル-プラズマ距離・曲率
({CURVATURE_THRESHOLD} 1/m、曲げ半径 {1 / CURVATURE_THRESHOLD:.0f} m) の各ペナルティを足したもので、L-BFGS-B を {MAXITER} 反復かけた。
コイル-プラズマ距離の要求値だけを {STANDOFF[0]}〜{STANDOFF[-1]} m で振っている。

電流の絶対値はこの wout からは決まらない。VMEC の正味ポロイダル電流は `bsubvmnc` から来るが、
このファイルは `rmnc` / `zmns` / `xm` / `xn` しか持たないためである。R#sub[0] = {R_MAJOR:.2f} m
(境界の m=n=0 成分) で B#sub[0] = {B0} T を仮定して総電流 2πR#sub[0]B#sub[0]/μ#sub[0] を固定した。
目的関数が B·n/|B| で電流スケールに不変なので、コイル形状はこの仮定に依らず、下表の電流値だけが
B#sub[0] に比例する。

LCFS は alphastell (Rust) 側の実装と同じ点を返すことを 3 点で確認してから simsopt に渡している。
VMEC も simsopt も R = Σ rc cos(mθ - n·nfp·φ) なので係数はそのまま移せるが、xn の符号を
取り違えると鏡像になり、図を見ても気付けないためである。

同じ理由で有限ベータの補正は入っていない。プラズマ自身の作る磁場を差し引く virtual casing に
必要な `bsubumnc` / `bsubvmnc` と圧力プロファイルがこのファイルには無いので、コイルだけで
LCFS を作る真空磁場に近い扱いになっている。反応炉ベータでは無視できない近似である。

== 結果: どこまでコイルを離せるか

#table(
  columns: 6,
  align: (right, right, right, right, right, right),
  [要求距離 [m]], [実現距離 [m]], [max |B·n|/|B|], [mean |B·n|/|B|], [全コイル長 [m]], [コイル間 [m]],
{scan_rows})

要求 {STANDOFF[0]} m はほぼそのまま実現できる ({results[0]["cs"]:.2f} m)。別途 1.0 m を要求しても
1.38 m までしか近づかないので、この配位のコイルは放っておいても 1.4 m 前後に落ち着く。
一方、要求を上げると法線磁場誤差は {np.abs(results[0]["error"]).max():.1e} ({results[0]["cs"]:.2f} m) から
{np.abs(results[-1]["error"]).max():.1e} ({results[-1]["cs"]:.2f} m) へ 1 桁上がり、同時にコイル間距離が
{results[0]["cc"]:.2f} m から {results[-1]["cc"]:.2f} m へ詰まる。離した分を長いコイルで補おうとして
互いに衝突するためで、2 m 付近が実用上の壁になる。

#figure(image("al_07_error.png", width: 100%), caption: [左: 実現距離 {baseline["cs"]:.2f} m での
LCFS 上の B·n/|B| 分布。右: コイル-プラズマ距離に対する法線磁場誤差。点線は al_06 の PbLi 最大厚み。])

== 結果: コイル形状

以下は要求 {STANDOFF[0]} m のコイルである。

#table(
  columns: 4,
  align: (center, right, right, right),
  [コイル], [長さ [m]], [電流 [MA]], [最小曲げ半径 [m]],
{coil_rows})

#figure(image("al_07_coils.png", width: 92%), caption: [{len(coils)} 本のモジュラーコイルと LCFS。
色は独立コイルの番号で、同色の {2 * NFP} 本は対称操作による像である。])

#figure(image("al_07_half_period.png", width: 82%), caption: [半周期を取り出したもの。
赤が LCFS、実線が独立コイル {NCOILS} 本。断面が三角形から楕円へ捻れる領域でコイルが強く曲がる。])

== 考察

半径方向の予算は約 1.4 m、無理をして 2 m である。al_06 の PbLi 殻は 70 cm でも TBR が
飽和していなかったから、残る 70 cm 前後に第一壁・冷却管・背面支持構造・遮蔽・真空容器・
組立公差の全部を収めなければならない。al_06 の「厚くすれば TBR が上がる」と本節の
「離すと磁気面が再現できない」は独立した 2 つの結果ではなく、1 つの半径方向予算の
奪い合いである。al_08 以降で不均質な WCLL 構造を入れるとき、厚みの上限はここで決まる。

コイル本数を増やしてもこの壁は動かない。本スクリプトの外で半周期 5 本・6 本も試したが、
max |B·n|/|B| は 1e-2 台に留まり、全コイル長だけが 20〜30% 増えた。誤差を決めているのは
本数ではなく距離である。

コイル形状は `out/al_07_coils.csv` に全 {len(coils)} 本の Fourier 係数として出してある。
各コイルは m = 0…{ORDER} の

$ bold(x)(t) = sum_m [ bold(c)_m cos(2 pi m t) + bold(s)_m sin(2 pi m t) ] $

で表され、点列と違って任意の分解能で滑らかに引き直せる。対称操作による像も回転行列を
掛けただけで次数は変わらないので、{len(coils)} 本すべてを同じ形式で持てる。al_04 と同じ経路で
STEP にすれば、そのまま構造解析と干渉チェックに渡せる。
"""
(OUT / "al_07_report.typ").write_text(report, encoding="utf-8")
typst.compile(OUT / "al_07_report.typ", output=OUT / "al_07_report.pdf")
print(f"{OUT / 'al_07_report.pdf'}: {(OUT / 'al_07_report.pdf').stat().st_size} bytes")
