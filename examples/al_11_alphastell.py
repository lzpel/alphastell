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
	step_sweep=torus(surface, make_sweep=(
		[[]]
	))
	write_step(step_sweep, out.with_suffix(".sweep.step"))


def torus(
	surface: SurfaceFourierRZ,
	make_surface: Callable[[float, float], float]|None=None,  # 磁気面法線に沿ったオフセット [m]。0 を返せば磁気面そのもの
	make_sweep: Tuple[List[float], List[List[float]]]|None=None, # 最初の要素はxy xはtheta方向 yはs方向 
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
		height=0.4
		width=0.5
		profile = make_sweep[0]

		paths = [[e for p in spine for e in guided(p)] for spine in projected_spines]
		return Geometry.sweep_geometry(profile, paths)
		

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