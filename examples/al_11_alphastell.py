import math
import pathlib
from typing import Callable, List, Tuple

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
	out.parent.mkdir(parents=True, exist_ok=True)
	step_surface=torus(surface, make_surface=lambda phi, theta: 0.0)
	write_step(step_surface, out.with_suffix(".surface.step"))
	step_sweep=torus(surface, make_sweep=(True, [-0.1, -0.2, 0.1, -0.2, 0.1, 0.2, -0.1, 0.2], [
		[angle for i in range(96) for angle in (math.tau * i / 96, theta)] for theta in (0.0, math.pi)
	]))
	write_step(step_sweep, out.with_suffix(".sweep.step"))


def torus(
	surface: SurfaceFourierRZ,
	make_surface: Callable[[float, float], float]|None=None,  # 磁気面法線に沿ったオフセット [m]。0 を返せば磁気面そのもの
	make_sweep: Tuple[bool, List[float], List[List[float]]]|None=None, # (閉曲線か, 断面 [x0,y0,...] で +x が磁気面法線 s 方向, spine ごとの [phi0,theta0,phi1,theta1,...])
	div_phi: int = 96,
	div_theta: int = 40,
	s: float = 1.0,  # LCFS (プラズマ最外縁)
) -> Geometry:
	if make_surface:
		def point(phi: float, theta: float) -> List[float]:
			p, n = surface.point_normal(phi, theta, s, False)
			return [p[i] + n[i] * make_surface(phi, theta) for i in range(3)]
		return Geometry.bspline_geometry([[point(math.tau * i / div_phi, math.tau * j / div_theta) for j in range(div_theta)] for i in range(div_phi)])
	if make_sweep:
		periodic, profile, spine_angles = make_sweep
		radius = max(math.hypot(profile[i], profile[i + 1]) for i in range(0, len(profile), 2))  # guide は向きにしか効かない (KeepContact なし) ので断面の外接円で足りる
		def path(phi: float, theta: float) -> List[float]:
			p, n = surface.point_normal(phi, theta, s, False)
			return [*p, *(p[i] + n[i] * radius for i in range(3))]  # spine と guide を交互に並べた 6N 形式
		paths = [[e for i in range(0, len(angles), 2) for e in path(angles[i], angles[i + 1])] for angles in spine_angles]
		return Geometry.sweep_geometry(periodic, profile, paths)
	raise ValueError("make_surface か make_sweep のどちらかを指定する")


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