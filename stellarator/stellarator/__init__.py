from .stellarator import *
import numpy as np
from .decorator import wrap_call

# python側でrust関数をwrapできるかのテスト
@wrap_call
def hello_numpy(f, array: np.ndarray) -> float:
	return f(array.sum())