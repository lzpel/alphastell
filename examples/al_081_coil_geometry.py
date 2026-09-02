"""実験8.1 コイル形状を掃引できるか

al_08 の stage-2 最適化はコイル中心線 (Fourier 係数) までしか出さない。
その gamma() 点列を sweep_geometry の経路に食わせ、矩形断面の導体ソリッドを STEP に起こす。
"""
import math
import os
import pathlib
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from al_08_coil_geometry import make_surface, optimize_coil

matplotlib.use("TkAgg")  # al_08 が import 時に Agg を強制するので、対話表示に戻す


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "alphastell" / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".step").name,
	width: float = 0.40,  # 導体断面のトロイダル幅 [m]。parastell の例 (width 40 cm) に合わせた
	height: float = 0.50,  # 導体断面の半径方向厚み [m]。同 (thickness 50 cm)。9.5 MA/コイルで約 48 A/mm²
) -> None:
	surface = make_surface(wout)
	result = optimize_coil(surface)
	spines = guided_spines(wout, [coil.curve.gamma().tolist() for coil in result["coils"]], math.sqrt(width**2 + height**2)/2)
	visualize_guided_spines(spines)
	# up = guide 方向 = LCFS 法線 (半径方向) が断面のローカル +X になるので、x に height、y に width を割る
	solids = sweep_guided_spines([-height / 2, -width / 2, height / 2, -width / 2, height / 2, width / 2, -height / 2, width / 2], spines)
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


def guided_spines(
	wout: pathlib.Path,
	spines_points: list[list[tuple[float, float, float]]],  # コイル 1 本あたりの中心線点列 (x, y, z)。対称像込み
	distance_between_spine_and_guide: float = 0.40,  # 導体断面のトロイダル幅 [m]。断面のローカル x
) -> None:  # alphastell.Geometry
	from alphastell import Geometry, SurfaceFourierRZ
	ret_spines_with_guide = []
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)
		for points in spines_points:
			point_center = np.mean(points, axis=0)
			phi, theta, s = math.atan2(point_center[1], point_center[0]), 0.0, 1.0
			points_with_guide = []
			for point in points:
				phi, theta = surface.nearest(phi, theta, s, point)  # 前の点の解を次の初期値にする継続法
				# 射影の足 (LCFS 上の点) は使わず、その点の法線だけもらう
				(nx, ny, nz) = surface.point_normal(phi, theta, s, True)[1]
				# spine はコイル点そのもの。guide はコイル点を LCFS 法線方向へずらした平行曲線
				points_with_guide.append([
					point[0],
					point[1],
					point[2],
					point[0] + nx * distance_between_spine_and_guide,
					point[1] + ny * distance_between_spine_and_guide,
					point[2] + nz * distance_between_spine_and_guide
				])
			ret_spines_with_guide.append(points_with_guide)
	return ret_spines_with_guide

def sweep_guided_spines(
	profile: list[float],  # 原点まわりの平面断面 [x0, y0, x1, y1, ...]。矩形なら 4 点 8 要素
	spines: list[list[list[float]]],  # guided_spines の出力 [ncoil][npoint][x, y, z, guidex, guidey, guidez]
) -> Any:  # alphastell.Geometry
	"""spine+guide を現行 sweep_geometry (Up 法) に食わせる暫定版。

	現 API は 1 本あたり up 1 個しか受けないので、始点の guide 方向を up に使う。
	点ごとの guide で捻りを制御する Auxiliary 版は cadrum 側の対応待ち。
	up = LCFS 法線が接線と平行に近づく箇所があれば掃引は落ちるが、それも診断のうち。
	"""
	from alphastell import Geometry
	spines=[[e for p in spine for e in p] for spine in spines]
	return Geometry.sweep_geometry(True, profile, spines)


def visualize_guided_spines(spines_with_guide: list[list[tuple[float, float, float]]]) -> None:
	array = np.array(spines_with_guide)  # [ncoil, npoint, 6]
	spine, guide = array[..., :3], array[..., 3:]
	figure = plt.figure()
	axes = figure.add_subplot(111, projection="3d")
	for spine_i, guide_i in zip(spine, guide):
		closed_spine = np.concatenate([spine_i, spine_i[:1]])
		closed_guide = np.concatenate([guide_i, guide_i[:1]])
		axes.plot(closed_spine[:, 0], closed_spine[:, 1], closed_spine[:, 2], color="tab:blue", linewidth=0.7)
		axes.plot(closed_guide[:, 0], closed_guide[:, 1], closed_guide[:, 2], color="tab:orange", linewidth=0.7)
		for a, b in zip(spine_i[::3], guide_i[::3]):  # 3 点に 1 本だけ描いて密度を抑える
			axes.plot([a[0], b[0]], [a[1], b[1]], [a[2], b[2]], color="tab:red", linewidth=0.6)
	flat = spine.reshape(-1, 3)
	axes.set_box_aspect(np.ptp(flat, axis=0))
	axes.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]", title="coil centerlines (blue), guide curves (orange), LCFS normals (red)")
	figure.savefig(pathlib.Path("out") / f"{pathlib.Path(__file__).stem}.spines_with_guide.png", dpi=150)
	len(os.getenv("SHOW","")) and plt.show()

if __name__ == "__main__":
	main()
