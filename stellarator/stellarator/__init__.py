from .stellarator import *
import numpy as np
from .decorator import wrap_call


def flatten_points(points: np.ndarray) -> List[float]:
	# points.shape が (N, M, 3) のとき、各点の座標を平坦化して返す。N: トロイダル方向分割数, M: ポロイダル方向分割数 3: 座標 (x, y, z)
	if len(points.shape) == 3 and points.shape[2] == 3:
		return [points.shape[0], points.shape[1], *points.flatten().tolist()]
	raise ValueError(f"points.shape must be (N, M, 3), but got {points.shape}")

@wrap_call
def loft_geometry(f, points: np.ndarray) -> Geometry:
	# 失敗は rust 側が ValueError を送出する (geometry::Error -> PyErr)
	return f(flatten_points(points))

@wrap_call
def bspline_geometry(f, points: np.ndarray) -> Geometry:
	return f(flatten_points(points))

# python側でrust関数をwrapできるかのテスト
@wrap_call
def hello_numpy(f, array: np.ndarray) -> float:
	return f(array.sum())