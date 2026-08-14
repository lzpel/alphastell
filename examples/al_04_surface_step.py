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

from stellarator import SurfaceRZFourier, Geometry

WOUT = pathlib.Path(__file__).resolve().parent.parent / "stellarator" / "wout_vmec.nc"
OUT_STEP = pathlib.Path("out/al_04_surface.step")

S = 1.0  # LCFS (プラズマ最外縁)
# 制御点は補間の節点になるので、al_03 の描画用格子ほど細かくしなくてよい。
# nfp=4 なので 128 分割で 1 周期あたり 32 点。
DIV_PHI = 128
DIV_THETA = 48

with open(WOUT, "rb") as f:
	surface = SurfaceRZFourier.load(f)

points = np.empty((DIV_PHI, DIV_THETA, 3))
for i in range(DIV_PHI):
	phi = math.tau * i / DIV_PHI
	for j in range(DIV_THETA):
		theta = math.tau * j / DIV_THETA
		# 法線は使わないので捨てる。use_surface は点の値に影響しない
		points[i, j], _ = surface.point_normal(phi, theta, S, True)

solid = Geometry.bspline_geometry(points)

OUT_STEP.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_STEP, "wb") as f:
	solid.write_step(f)
print(f"{OUT_STEP}: {DIV_PHI} x {DIV_THETA} 制御点 (s={S}), {OUT_STEP.stat().st_size} bytes")
