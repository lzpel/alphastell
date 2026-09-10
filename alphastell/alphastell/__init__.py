from .alphastell import *
import numpy as np
from typing import List, Union
from .decorator import wrap_call


def flatten_points(points: Union[np.ndarray, list]) -> List[float]:
	points = np.asarray(points)
	if points.ndim == 3 and points.shape[2] == 3:
		return [points.shape[0], points.shape[1], *points.flatten().tolist()]
	raise ValueError(f"points.shape must be (N, M, 3), but got {points.shape}")
@wrap_call(Geometry)
def loft_geometry(f, points: np.ndarray) -> Geometry:
	# 失敗は rust 側が ValueError を送出する (geometry::Error -> PyErr)
	return f(flatten_points(points))

@wrap_call(Geometry)
def bspline_geometry(f, points: np.ndarray) -> Geometry:
	return f(flatten_points(points))

# python側でrust関数をwrapできるかのテスト
@wrap_call(None)
def hello_numpy(f, array: np.ndarray) -> float:
	return f(array.sum())