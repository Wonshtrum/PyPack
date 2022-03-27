import struct
from inspect import currentframe as frame


class TWD:
	def __init__(self, pre=id):
		self.id = 0
		self.obj_to_id = {}
		self.id_to_obj = {}
		self.pre = pre

	def clear(self):
		self.id = 0
		self.obj_to_id.clear()
		self.id_to_obj.clear()

	def add(self, obj, *args):
		if self.pre(obj) in self.obj_to_id:
			return False
		self.obj_to_id[self.pre(obj)] = (self.id, args)
		self.id_to_obj[self.id] = (obj, args)
		self.id += 1
		return True

	def from_id(self, id, error=True):
		if error and id not in self.id_to_obj:
			raise ValueError(f"{id} isn't registerd in ctx")
		return self.id_to_obj.get(id)

	def from_obj(self, obj, error=True):
		if error and self.pre(obj) not in self.obj_to_id:
			raise ValueError(f"{obj} isn't registerd in ctx")
		return self.obj_to_id.get(self.pre(obj))


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
				return True
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

	def pull_any(self):
		print(f"PULL ANY")
		value, is_ref = self.read_guard()
		if is_ref:
			print(f" `-> GUARD_REF_{value}")
			obj, _ = self.refs.from_id(value)
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
		return ctor(ctx.pull_any() for _ in range(l))
	def write(obj, ctx):
		ctx._push("I", len(obj))
		for e in obj:
			ctx.push(e)
	return ctor, True, _read or read, _write or write

def write_complex(obj, ctx):
	ctx._push("2d", obj.real, obj.imag)
def write_range(obj, ctx):
	ctx._push("3l", obj.start, obj.stop, obj.step)
def read_list(ctx):
	l, = ctx._pull("I")
	obj = [None]*l
	ctx.add_ref(obj)
	for i in range(l):
		obj[i] = ctx.pull_any()
	return obj


nonetype = type(None)
function = type(lambda:0)
primary = [
	nonetype, bool, int, float, complex, range,		# atom, no-mut
	list,											# iter, mut
	tuple, set, frozenset, bytearray,				# iter, no-mut-like
	str, bytes,
	dict,
]


ctx = Context()
ctx.add_ctor(*std_atom(nonetype, "?"))
ctx.add_ctor(*std_atom(bool, "?"))
ctx.add_ctor(*std_atom(int, "l"))
ctx.add_ctor(*std_atom(float, "d"))
ctx.add_ctor(*std_atom(complex, "2d", _write=write_complex))
ctx.add_ctor(*std_atom(range, "3l", _write=write_range))
ctx.add_ctor(*std_iter(list, _read=read_list))
ctx.add_ctor(*std_iter(tuple))
ctx.add_ctor(*std_iter(set))
ctx.add_ctor(*std_iter(frozenset))

a=[0,1,2,3,4]
a[1]=a
ctx.push(a)
ctx.clear()
ctx.pull_any()
