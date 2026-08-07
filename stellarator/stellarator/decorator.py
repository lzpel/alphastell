import functools, inspect, sys

def wrap_call(fn):
	name = fn.__name__
	# この時点では新しい def の代入がまだ済んでいないので、同名には元の関数が残っている
	frame = sys._getframe(1)
	if name in frame.f_locals:        # module 直下なら f_locals is f_globals
		original = frame.f_locals[name]
	else:
		raise NameError(f"{name} is undefined")

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		return fn(original, *args, **kwargs)

	sig = inspect.signature(fn)       # 注入した f を公開シグネチャから削る
	wrapper.__signature__ = sig.replace(parameters=list(sig.parameters.values())[1:])
	wrapper.__wrapped__ = original
	return wrapper