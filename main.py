import struct
from inspect import currentframe as frame


class TWD:
	def __init__(self, pre=id):
		self.id = 0
		self.obj_to_id = {}
		self.id_to_obj = {}
		self.watchers = {}
		self.pre = pre

	def clear(self):
		self.id = 0
		self.obj_to_id.clear()
		self.id_to_obj.clear()

	def reserve(self):
		self.id += 1
		return self.id-1

	def watch(self, id, func):
		if id in self.watchers:
			self.watchers[id].append(func)
		else:
			self.watchers[id] = [func]

	def add(self, obj, *args, id=None):
		if self.pre(obj) in self.obj_to_id:
			return False
		if id is None:
			id = self.id
			self.id += 1
		if id in self.watchers:
			for callback in self.watchers[id]:
				callback(obj, *args)
			del self.watchers[id]
		self.obj_to_id[self.pre(obj)] = (id, args)
		self.id_to_obj[id] = (obj, args)
		return True

	def from_id(self, id, error=True):
		if error and id not in self.id_to_obj:
			raise ValueError(f"{id} isn't registerd in ctx")
		return self.id_to_obj.get(id)

	def from_obj(self, obj, error=True):
		if error and self.pre(obj) not in self.obj_to_id:
			raise ValueError(f"{obj} isn't registerd in ctx")
		return self.obj_to_id.get(self.pre(obj))


class LazyRef:
	def __init__(self, id):
		self.id = id
	def callback(self, obj, index):
		def wrapper(e, *args):
			print(f"CAUGHT_REF_{self.id}")
			obj[index] = e
		return wrapper
	def __repr__(self):
		return f"LAZY_REF_{self.id}"


class Context:
	def __init__(self, buff=b""):
		self.ctors  = TWD()
		self.refs   = TWD()
		self.buff   = buff
		self.offset = 0
		self.guard_fmt = "I"

	def clear(self):
		self.refs.clear()

	def add_ctor(self, ctor, mut, read, write):
		return self.ctors.add(ctor, mut, read, write)
	def add_ref(self, ref):
		return self.refs.add(ref)

	def _push(self, fmt, *args):
		self.buff += struct.pack(fmt, *args)

	def _pull(self, fmt):
		res = struct.unpack_from(fmt, self.buff, self.offset)
		print(f" | {struct.pack(fmt, *res).hex()}-{fmt}->{res}")
		self.offset += struct.calcsize(fmt)
		return res

	def write_guard(self, value, is_ref):
		self._push(self.guard_fmt, value<<1|is_ref)
	def read_guard(self):
		value, = self._pull(self.guard_fmt)
		return value>>1, value&1

	def push(self, obj, can_ref=True):
		ctor = type(obj)
		id, (mut, read, write) = self.ctors.from_obj(ctor)
		if mut and can_ref:
			ref = self.refs.from_obj(obj, error=False)
			if ref is not None:
				self.write_guard(ref[0], is_ref=True)
				return
			self.add_ref(obj)
		self.write_guard(id, is_ref=False)
		write(obj, self)

	def pull(self, ctor):
		print(f"PULL {ctor}")
		id, (mut, read, write) = self.ctors.from_obj(ctor)
		obj = read(self)
		print(f" `-> {obj}")
		if mut:
			self.add_ref(obj)
		return obj

	def pull_any(self, lazy_ref=False):
		print(f"PULL ANY")
		value, is_ref = self.read_guard()
		if is_ref:
			print(f" `-> GUARD_REF_{value}")
			ref = self.refs.from_id(value, error=not lazy_ref)
			if ref is None:
				obj = LazyRef(value)
			else:
				obj = ref[0]
		else:
			ctor, (mut, read, write) = self.ctors.from_id(value)
			print(f" `-> GUARD_TYP_{ctor.__name__}")
			obj = read(self)
			if mut:
				self.add_ref(obj)
		print(f" `-> {obj}")
		return obj


def std_atom(ctor, fmt, _read=None, _write=None):
	def read(ctx):
		args = ctx._pull(fmt)
		return ctor(*args)
	def write(obj, ctx):
		ctx._push(fmt, obj)
	return ctor, False, _read or read, _write or write

def std_iter(ctor, _read=None, _write=None):
	def read(ctx):
		l, = ctx._pull("I")
		id = ctx.refs.reserve()
		obj = ctor(ctx.pull_any() for _ in range(l))
		ctx.refs.add(obj, id=id)
		return obj
	def write(obj, ctx):
		ctx._push("I", len(obj))
		for e in obj:
			ctx.push(e)
	return ctor, True, _read or read, _write or write

def std_char(ctor, pre=lambda x:x, post=lambda x:x, _read=None, _write=None):
	def read(ctx):
		l, = ctx._pull("I")
		o = bytearray(ctx._pull("B")[0] for _ in range(l))
		print(o)
		return post(o)
	def write(obj, ctx):
		obj = pre(obj)
		ctx._push("I", len(obj))
		for e in obj:
			ctx._push("B", e)
	return ctor, True, _read or read, _write or write


def write_complex(obj, ctx):
	ctx._push("2d", obj.real, obj.imag)
def write_range(obj, ctx):
	ctx._push("3l", obj.start, obj.stop, obj.step)
def write_none(obj, ctx):
	pass
def read_list(ctx):
	l, = ctx._pull("I")
	obj = [None]*l
	ctx.add_ref(obj)
	for i in range(l):
		e = ctx.pull_any(lazy_ref=True)
		obj[i] = e
		if isinstance(e, LazyRef):
			ctx.refs.watch(e.id, e.callback(obj, i))
	return obj


nonetype = type(None)
function = type(lambda:0)
primary = [
	nonetype, bool, int, float, complex, range,		# atom, no-mut
	list,											# iter, mut
	tuple, set, frozenset,							# iter, no-mut-like
	str, bytes, bytearray,							# iter, no-mut-like, const subtype
	dict,
]


ctx = Context()
ctx.add_ctor(*std_atom(nonetype, "", _write=write_none))
ctx.add_ctor(*std_atom(bool, "?"))
ctx.add_ctor(*std_atom(int, "l"))
ctx.add_ctor(*std_atom(float, "d"))
ctx.add_ctor(*std_atom(complex, "2d", _write=write_complex))
ctx.add_ctor(*std_atom(range, "3l", _write=write_range))
ctx.add_ctor(*std_iter(list, _read=read_list))
ctx.add_ctor(*std_iter(tuple))
ctx.add_ctor(*std_iter(set))
ctx.add_ctor(*std_iter(frozenset))
ctx.add_ctor(*std_char(str, pre=str.encode, post=lambda x:x.decode()))
ctx.add_ctor(*std_char(bytes, post=bytes))
ctx.add_ctor(*std_char(bytearray))

b=[None, 42, 3.14]
a=(0,b,b,3,"♟️", b"\xe2\x99\x9f\xef\xb8\x8f", bytearray(b"\xe2\x99\x9f\xef\xb8\x8f"))
b.append(a)
ctx.push(a)
ctx.clear()
ctx.pull_any()
