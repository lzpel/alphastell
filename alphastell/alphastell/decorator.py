import functools, inspect, sys

def wrap_call(namespace):
	def deco(fn):
		name = fn.__name__
		if namespace:
			original = getattr(namespace, name)
		else:
			original = sys._getframe(1).f_locals[name]

		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			return fn(original, *args, **kwargs)

		sig = inspect.signature(fn)       # 注入した f を公開シグネチャから削る
		wrapper.__signature__ = sig.replace(parameters=list(sig.parameters.values())[1:])
		wrapper.__wrapped__ = original
		if isinstance(namespace, type):       # クラスなら同じ名前に差し戻す
			setattr(namespace, name, staticmethod(wrapper))
		return wrapper
	return deco