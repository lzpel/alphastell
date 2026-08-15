
from alphastell import loft_geometry, bspline_geometry
import numpy as np

# 退化しない最小構成: 断面2つ x 断面あたり3点 (非共線)。三角柱。
# 断面あたり2点だと polygon が面を囲めず cadrum が失敗する
points = np.array([
	[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
	[[0, 0, 1], [1, 0, 1], [0, 1, 1]],
], dtype=float) # shape (2, 3, 3)

a = loft_geometry(points)
b = bspline_geometry(points)
print(f"loft: {a}\nbspline: {b}")
