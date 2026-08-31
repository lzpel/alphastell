"""実験8.1 コイル形状を掃引できるか"""
from al_08_coil_geometry import optimize_coil, make_surface
import pathlib
def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".pdf").name,
) -> list[dict[str, Any]]:
	# 最適化まで
	surface = make_surface(wout)
	result = optimize_coil(surface)
	print(result)
def geometry(
	wout: pathlib.Path,
	coils
):	
	from alphastell import SurfaceFourierRZ, Geometry
	# sweep_geometryでcoilsに沿って掃引させてstepを書き出して、とりあえず15cm x 10cmの長方形プロファイルで


TEMPLATE="""
show something
"""

if __name__ == "__main__":
	main()