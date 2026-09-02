"""実験8.1 コイル形状を掃引できるか

al_08 の stage-2 最適化はコイル中心線 (Fourier 係数) までしか出さない。
その gamma() 点列を sweep_geometry の経路に食わせ、矩形断面の導体ソリッドを STEP に起こす。
"""
import math
import pathlib
from typing import Any

import numpy as np

from al_08_coil_geometry import make_surface, optimize_coil


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".step").name,
	width: float = 0.40,  # 導体断面のトロイダル幅 [m]。parastell の例 (width 40 cm) に合わせた
	height: float = 0.50,  # 導体断面の半径方向厚み [m]。同 (thickness 50 cm)。9.5 MA/コイルで約 48 A/mm²
) -> None:
	surface = make_surface(wout)
	result = optimize_coil(surface)
	solids = geometry(result["coils"], width, height)
	out.parent.mkdir(parents=True, exist_ok=True)
	for path, write in ((out, solids.write_step), (out.with_suffix(".png"), solids.write_png)):
		with open(path, "wb") as f:
			write(f)
		print(f"{path}: {len(solids)} solids, {path.stat().st_size} bytes")
	# 断面積 x 中心線長。断面が法平面に乗っていれば掃引体積はこれに一致する (al_09 と同じ検査)
	exact = [width * height * float(np.linalg.norm(np.diff(c.curve.gamma(), axis=0, append=c.curve.gamma()[:1]), axis=1).sum()) for c in result["coils"]]
	volume = solids.volume()
	error = [(v / e - 1.0) * 100 for v, e in zip(volume, exact)]
	print(f"volume {min(volume):.4f}..{max(volume):.4f} m^3, error vs area x length {min(error):+.2f}..{max(error):+.2f} %")


def geometry(
	coils: list[Any],  # simsopt の Coil (対称像込み)。curve.gamma() の点列を掃引経路にする
	width: float = 0.40,  # 導体断面のトロイダル幅 [m]。断面のローカル x
	height: float = 0.50,  # 導体断面の半径方向厚み [m]。断面のローカル y
	npoint: int = 48,  # 1 本あたりの経路点数。gamma() から等間隔に間引く
) -> Any:  # alphastell.Geometry
	"""コイル中心線に矩形断面を掃引して導体ソリッドにする。

	up はコイル重心のトロイダル角 phi での e_phi にとる。接線が up と平行になる箇所は
	無いので掃引は通るが、Up 法は断面を「接線の up 直交成分」に立てるため、最適化後の
	コイルは R-z 面から最大 57 度傾き、断面が経路と直交せず体積が 1-2 割減る (main の検査で出る)。
	閉ループなので始点を末尾で繰り返さない (周期性はスプラインの基底に入る)。
	"""
	from alphastell import Geometry
	profile = [-width / 2, -height / 2, width / 2, -height / 2, width / 2, height / 2, -width / 2, height / 2]
	paths = []
	for coil in coils:
		points = coil.curve.gamma()
		points = points[np.linspace(0, len(points), npoint, endpoint=False).astype(int)]
		phi = math.atan2(*points.mean(axis=0)[[1, 0]])
		paths.append([-math.sin(phi), math.cos(phi), 0.0] + points.ravel().tolist())
	return Geometry.sweep_geometry(True, profile, *paths)


if __name__ == "__main__":
	main()
