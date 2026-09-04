#!/usr/bin/env python3
"""VMEC の LCFS (s=1) を (φ, θ) 格子で走査し、bspline_geometry で CAD ソリッドにして STEP に書く。

al_03 が出した点群を、そのまま W2 の geometry モジュールに流すだけの経路確認。
cadrum の bspline は u (軸0, トロイダル) が u_periodic=true、v (軸1, ポロイダル) は常に閉じるので、
φ=2π と θ=2π の重複点は入れない (al_03 の格子と同じ並び)。

リポジトリルートで:

    make al-04
"""

import math
import pathlib

import numpy as np

from alphastell import SurfaceFourierRZ, Geometry


def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".step").name,
	s: float = 1.0,  # LCFS (プラズマ最外縁)
	# 制御点は補間の節点になるので、al_03 の描画用格子ほど細かくしなくてよい。
	div_phi: int = 128,  # nfp=4 なので 128 分割で 1 周期あたり 32 点
	div_theta: int = 48,
) -> None:
	with open(wout, "rb") as f:
		surface = SurfaceFourierRZ.load(f)

	points = np.empty((div_phi, div_theta, 3))
	for i, j in np.ndindex(div_phi, div_theta):
		# 法線は使わないので捨てる。use_surface は点の値に影響しない
		points[i, j], _ = surface.point_normal(math.tau * i / div_phi, math.tau * j / div_theta, s, True)

	out.parent.mkdir(parents=True, exist_ok=True)
	with open(out, "wb") as f:
		Geometry.bspline_geometry(points).write_step(f)
	print(f"{out}: {div_phi} x {div_theta} 制御点 (s={s}), {out.stat().st_size} bytes")


if __name__ == "__main__":
	main()
