import math
import pathlib

import numpy as np

from al_08_coil_geometry import guided_spines, make_surface, optimize_coil, sweep_guided_spines, visualize_guided_spines


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".step").name,
	width: float = 0.40,  # 導体断面のトロイダル幅 [m]。parastell の例 (width 40 cm) に合わせた
	height: float = 0.50,  # 導体断面の半径方向厚み [m]。同 (thickness 50 cm)。9.5 MA/コイルで約 48 A/mm²
) -> None:
	surface = make_surface(wout)
	result = optimize_coil(surface)
	spines = guided_spines(wout, [coil.curve.gamma().tolist() for coil in result["coils"]], math.sqrt(width**2 + height**2) / 2)
	visualize_guided_spines(spines, pathlib.Path("out") / f"{pathlib.Path(__file__).stem}.guided_spines.png")
	# guide 方向 = LCFS 法線 (半径方向) が断面のローカル +X になるので、x に height、y に width を割る
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


if __name__ == "__main__":
	main()
