import math
import pathlib
from typing import Callable

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
	out.parent.mkdir(parents=True, exist_ok=True)
	write_step(torus(surface, lambda phi, theta: 0.0), out.with_suffix(".step"))


def torus(
	surface: SurfaceFourierRZ,
	offset: Callable[[float, float], float],  # 磁気面法線に沿ったオフセット [m]。0 を返せば磁気面そのもの
	div_phi: int = 96,
	div_theta: int = 40,
	s: float = 1.0,  # LCFS (プラズマ最外縁)
) -> Geometry:
	def point(phi: float, theta: float) -> list[float]:
		p, n = surface.point_normal(phi, theta, s, False)
		return [p[i] + n[i] * offset(phi, theta) for i in range(3)]
	return Geometry.bspline_geometry([[point(math.tau * i / div_phi, math.tau * j / div_theta) for j in range(div_theta)] for i in range(div_phi)])


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