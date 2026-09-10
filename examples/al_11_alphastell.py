import functools
import math
import pathlib
from typing import Callable, List, Tuple, Union

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
	out.parent.mkdir(parents=True, exist_ok=True)
	step_layers=make_on_surface(surface, make_layers=lambda phi, theta: [0.0, 0.1, 0.5])
	write_step(functools.reduce(Geometry.concat, step_layers), out.with_suffix(".layers.step"))
	step_sweep=make_on_surface(surface, make_sweep=(True, [-0.1, -0.2, 0.1, -0.2, 0.1, 0.2, -0.1, 0.2], [
		[angle for i in range(96) for angle in (math.tau * i / 96, theta)] for theta in (0.0, math.pi)
	]))
	write_step(step_sweep, out.with_suffix(".sweep.step"))

def material_mix(*args: List[Tuple[Union[str, List[Tuple[str, float]]], float]])->List[Tuple[str, float]]:
	ret: List[Tuple[str, float]]=[("He", 1.0)]
	# 上を書いて
	elements: list[str] = ["He", "Fe", "Cr", "W", "Pb", "Li", "Si", "C", "H", "O", "Cu", "Nb", "Sn", "N"]
	if all(i[0] in elements for i in ret) and abs(sum(i[1] for i in ret)-1)<0.01:
		return ret
	else:
		raise ValueError("invalid material composition")

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