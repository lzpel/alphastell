import functools
import itertools
import math
import pathlib

from typing import Callable, List, Tuple

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
	out.parent.mkdir(parents=True, exist_ok=True)
	layers = make_stellarator(surface)
	for name, geometry in layers:
		write_step(geometry, out.with_suffix(f".{name}.step"))
	write_step(functools.reduce(Geometry.concat, (g for _, g in layers)), out.with_suffix(".layers.step"))
	step_sweep=make_on_surface(surface, make_sweep=(True, [-0.1, -0.2, 0.1, -0.2, 0.1, 0.2, -0.1, 0.2], [
		[angle for i in range(96) for angle in (math.tau * i / 96, theta)] for theta in (0.0, math.pi)
	]))
	write_step(step_sweep, out.with_suffix(".sweep.step"))


def make_stellarator(
	surface: SurfaceFourierRZ,
	homogenize: bool=True,
	radial_build: List[Tuple[str, List[List[float]]]] = [  # 層名と厚さ行列 [m]。行がトロイダル 1 周期、列がポロイダル 1 周。al_10 の parastell_cad_to_dagmc_example と同じ値
		("chamber", [[0.0]]),  # 厚さ 0 なので最内の境界そのもの。s<=wall_s の詰まったソリッドになる
		("first_wall", [[0.05]]),
		("breeder", [
			[0.75, 0.75, 0.75, 0.25, 0.25, 0.25, 0.75, 0.75, 0.75],
			[0.75, 0.75, 0.75, 0.25, 0.25, 0.75, 0.75, 0.75, 0.75],
			[0.75, 0.75, 0.25, 0.25, 0.75, 0.75, 0.75, 0.75, 0.75],
			[0.65, 0.25, 0.25, 0.65, 0.75, 0.75, 0.75, 0.75, 0.65],
			[0.45, 0.45, 0.75, 0.75, 0.75, 0.75, 0.75, 0.45, 0.45],
			[0.65, 0.75, 0.75, 0.75, 0.75, 0.65, 0.25, 0.25, 0.65],
			[0.75, 0.75, 0.75, 0.75, 0.75, 0.25, 0.25, 0.75, 0.75],
			[0.75, 0.75, 0.75, 0.75, 0.25, 0.25, 0.75, 0.75, 0.75],
			[0.75, 0.75, 0.75, 0.25, 0.25, 0.25, 0.75, 0.75, 0.75],
		]),
		("back_wall", [[0.05]]),
		("shield", [[0.50]]),
		("vacuum_vessel", [[0.10]]),
	],
	coils_file: pathlib.Path = pathlib.Path(__file__).resolve().parent / "coils.example",
	s: float = 1.08,  # 第一壁内面の規格化磁束面ラベル。LCFS の少し外
	div_phi: int = 96, #192,　計算高速化の一時的処置
	div_theta: int = 40, #80, 計算高速化の一時的処置
) -> List[Tuple[str, Geometry]]:
	thicknesses = [interpolator(matrix) for _, matrix in radial_build]  # 層ごとに 1 回だけ構築する。点ごとに作ると格子の前処理が div_phi*div_theta 回走る
	def make_layers(phi: float, theta: float) -> List[float]:
		return list(itertools.accumulate(f(phi * surface.frequency0, theta) for f in thicknesses))
	if homogenize:
		layers=list(zip([name for name, _ in radial_build], make_on_surface(surface, make_layers=make_layers, s=s, div_phi=div_phi, div_theta=div_theta)))
	else:
		layers=[]# not yet implemented
	if homogenize:
		coils=[("magnets", make_coils(surface, coils_file))]  # 40 本を 1 つの Geometry にまとめるので要素は 1 つ
	else:
		coils=[]# not yet implemented
	return layers+coils


def make_coils(
	surface: SurfaceFourierRZ,
	coils_file: pathlib.Path,  # MAKEGRID 形式のフィラメント。x y z 電流 の 4 列で、群番号と名前が付く行が 1 本の終端
	width: float = 0.40,  # 断面のトロイダル幅 [m]。ローカル +y。al_10 の magnet_width と同じ
	height: float = 0.50,  # 断面の半径方向厚み [m]。ローカル +x = guide 方向。al_10 の magnet_thickness と同じ
	sample_mod: int = 6,  # フィラメントの点を何点おきに掃引に使うか
) -> Geometry:
	filaments, points = [], []
	for line in coils_file.read_text(encoding="utf-8").splitlines():
		columns = line.split()
		if len(columns) < 4:  # periods / begin filament / mirror NIL / end
			continue
		points.append([float(v) for v in columns[:3]])
		if len(columns) > 4:  # 終端行は先頭と同じ点。周期 B-spline は始終点の重複を許さないので落とす
			filaments.append(points[:-1][::sample_mod])
			points = []
	paths = [[e for p in spine for e in p] for spine in project_spines(surface, filaments, math.sqrt(width**2 + height**2) / 2)]
	profile = [-height / 2, -width / 2, height / 2, -width / 2, height / 2, width / 2, -height / 2, width / 2]
	return Geometry.sweep_geometry(True, profile, paths)


def project_spines(  # al_08_coil_geometry.py からのコピー。wout パスではなく読み込み済みの surface を受ける点だけが違う
	surface: SurfaceFourierRZ,
	spines_points: list[list[tuple[float, float, float]]],  # コイル 1 本あたりの中心線点列 (x, y, z)。対称像込み
	distance: float = -1, # 正ならガイドと線の距離、負なら射影先そのもの
	s: float = 1.0,  # 射影先の磁束面。LCFS
) -> list[list[tuple[float, float, float, float, float, float]]]:  # 中心線の各点に LCFS 上の最近傍点を並べて [x, y, z, projectedx, projectedy, projectedz] にする
	ret_projected_spines = []
	for points in spines_points:
		point_center = np.mean(points, axis=0)
		phi, theta = math.atan2(point_center[1], point_center[0]), 0.0
		projected_points = []
		for point in points:
			phi, theta = surface.nearest(phi, theta, s, point)  # 前の点の解を次の初期値にする継続法
			p, n = surface.point_normal(phi, theta, s, SurfaceFourierRZ.NORMAL_SURFACE)
			projected_points.append([*point, *[point[i]-distance*n[i] if distance>0 else p[i] for i in range(3)]])  # 射影の足だけもらう
		ret_projected_spines.append(projected_points)
	return ret_projected_spines


def interpolator(
	matrix: List[List[float]],
	method: str = "pchip",  # 厚さ行列の格子間の繋ぎ方。parastell の InVesselBuild の既定と同じ
) -> Callable[[float, float], float]:
	grid = np.array(matrix, dtype=float)
	if grid.min() == grid.max():  # 一様層。RegularGridInterpolator は軸あたり 2 点 (pchip は 4 点) を要求するので 1x1 を通せない
		return lambda phi, theta: float(grid.flat[0])
	axes = tuple(np.linspace(0.0, math.tau, n) for n in grid.shape)  # 行列の両端は同じ点。定義域 [0, tau] に剰余で畳んで周期性を閉じる
	interpolate = RegularGridInterpolator(axes, grid, method=method)
	return lambda phi, theta: float(interpolate((phi % math.tau, theta % math.tau)))


def make_on_surface(
	surface: SurfaceFourierRZ,
	make_layers: Callable[[float, float], List[float]]|None=None,  # 磁気面法線に沿った層境界のオフセット [m] を内側から順に。[0.0] を返せば磁気面そのもの
	make_sweep: Tuple[bool, List[float], List[List[float]]]|None=None, # (閉曲線か, 断面 [x0,y0,...] で +x が磁気面法線 s 方向, spine ごとの [phi0,theta0,phi1,theta1,...])
	div_phi: int = 96,
	div_theta: int = 40,
	s: float = 1.0,  # LCFS (プラズマ最外縁)
) -> Geometry|List[Geometry]:
	if make_layers:
		def point(layer: int, phi: float, theta: float) -> List[float]:
			p, n = surface.point_normal(phi, theta, s, SurfaceFourierRZ.NORMAL_PLANAR)
			return [p[j] + n[j] * make_layers(phi, theta)[layer] for j in range(3)]
		raw_layers = [
			Geometry.bspline_geometry([[point(layer, math.tau * i / div_phi, math.tau * j / div_theta) for j in range(div_theta)] for i in range(div_phi)])
			for layer in range(len(make_layers(0, 0)))
		]
		return [raw_layers[0], *(outer.boolean_subtract(inner) for inner, outer in zip(raw_layers, raw_layers[1:]))]  # 隣り合う要素同士をくりぬいていく
	if make_sweep:
		periodic, profile, spine_angles = make_sweep
		radius = max(math.hypot(profile[i], profile[i + 1]) for i in range(0, len(profile), 2))  # guide は断面の向きを決めるだけ (KeepContact なし) なので断面の外接円で足りる
		def path(phi: float, theta: float) -> List[float]:
			p, n = surface.point_normal(phi, theta, s, SurfaceFourierRZ.NORMAL_SURFACE)
			return [*p, *(p[i] + n[i] * radius for i in range(3))]  # spine と guide を交互に並べた 6N 形式
		paths = [[e for i in range(0, len(angles), 2) for e in path(angles[i], angles[i + 1])] for angles in spine_angles]
		return Geometry.sweep_geometry(periodic, profile, paths)
	raise ValueError("make_layers か make_sweep のどちらかを指定する")


def write_step(
	geometry: Geometry,
	out: pathlib.Path,
) -> None:
	with open(out, "wb") as fs, open(out.with_suffix(".png"), "wb") as fp:
		geometry.write_step(fs)
		geometry.write_png(fp)
	print(f"{out}: {out.stat().st_size} bytes")


if __name__ == "__main__":
	main()