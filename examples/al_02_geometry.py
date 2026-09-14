import math
import pathlib

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".step").name,
	s: float = 1.0,  # LCFS (プラズマ最外縁)
	div_phi: int = 64,  # bspline の制御点と loft の断面数。loft は断面間が 72° 以上開くと潰れる
	div_theta: int = 32,
	theta_center: float = math.pi / 2,  # 切り抜く帯のポロイダル中心
	theta_width: float = 0.8,  # 帯のポロイダル幅 [rad]
	s_inner: float = 0.5,  # 型の内縁の磁束面
	margin: float = 0.3,  # 型の外縁を s の面から法線方向にはみ出させる距離 [m]。s>1 に外挿すると高次モードが暴れて断面が自己交差する
	div_arc: int = 8,  # 型の断面で外側と内側の弧をそれぞれ刻む点数
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
	def point(phi: float, theta: float, s: float, offset: float = 0.0) -> list[float]:
		p, n = surface.point_normal(phi, theta, s, SurfaceFourierRZ.NORMAL_PLANAR)  # 断面内の法線なので押し出しても phi 一定の平面に乗る
		return [p[j] + n[j] * offset for j in range(3)]
	plasma = Geometry.bspline_geometry([[point(math.tau * i / div_phi, math.tau * j / div_theta, s) for j in range(div_theta)] for i in range(div_phi)])
	thetas = [theta_center + theta_width * (k / (div_arc - 1) - 0.5) for k in range(div_arc)]
	cutter = Geometry.loft_geometry([  # 断面は同じ phi の外側の弧と内側の弧を往復する扇形。loft はトロイダル方向に閉じるので 1 周の帯になる
		[*(point(math.tau * i / div_phi, theta, s, margin) for theta in thetas), *(point(math.tau * i / div_phi, theta, s_inner) for theta in reversed(thetas))]
		for i in range(div_phi)
	])
	cut = plasma.boolean_subtract(cutter)
	out.parent.mkdir(parents=True, exist_ok=True)
	for name, geometry in (("plasma", plasma), ("cutter", cutter), ("cut", cut)):
		path = out.with_suffix(f".{name}.step")
		with open(path, "wb") as fs, open(path.with_suffix(".png"), "wb") as fp:
			geometry.write_step(fs)
			geometry.write_png(fp)
		print(f"{path}: volume={geometry.volume()} {path.stat().st_size} bytes")


if __name__ == "__main__":
	main()
