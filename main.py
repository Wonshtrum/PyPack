import struct
from inspect import currentframe as frame


class TWD:
	def default_pre(x):
		if isinstance(x, (str, bytes, bytearray)):
			return x
		return id(x)
	def __init__(self, pre=default_pre):
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


class uint:
	pass
def add_flags(value, *flags):
	for f in flags:
		value = value<<1|bool(f)
	return value
def get_flags(value, n):
	flags = [value&(1<<i) for i in range(n)]
	return (value>>n, *flags)


class Context:
	def __init__(self, buff=b""):
		self.ctors  = TWD()
		self.refs   = TWD()
		self.buff   = buff
		self.offset = 0

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
		self.push_raw(uint, add_flags(value, is_ref))
	def read_guard(self):
		return get_flags(self.pull(uint), 1)

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

	def push_raw(self, ctor, obj, can_ref=True):
		id, (mut, read, write) = self.ctors.from_obj(ctor)
		if mut and can_ref:
			self.add_ref(obj)
		write(obj, self)

	def pull(self, ctor, can_ref=True):
		print(f"PULL {ctor}")
		id, (mut, read, write) = self.ctors.from_obj(ctor)
		obj = read(self)
		if mut and can_ref:
			self.add_ref(obj)
		print(f" `-> {obj}")
		return obj

	def pull_any(self, can_ref=True, lazy_ref=False):
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
			if mut and can_ref:
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

def is_typed(obj, ctx):
	if len(obj)<2:
		return False
	typ = type(next(iter(obj)))
	if all(type(_)==typ for _ in obj) and\
		all(ctx.refs.from_obj(_, error=False) is None for _ in obj):
		id, (ctor, read, write) = ctx.ctors.from_obj(typ)
		return id, write
	return False

def std_iter(ctor, _read=None, _write=None):
	def read(ctx):
		l, typed = get_flags(ctx.pull(uint), 1)
		id = ctx.refs.reserve()
		if typed:
			id = ctx.pull(uint)
			sub_ctor, (id, read, write) = ctx.ctors.from_id(id)
			obj = ctor(read(ctx) for _ in range(l))
		else:
			obj = ctor(ctx.pull_any() for _ in range(l))
		ctx.refs.add(obj, id=id)
		return obj
	def write(obj, ctx):
		typed = is_typed(obj, ctx)
		ctx.push_raw(uint, add_flags(len(obj), typed))
		if typed:
			id, write = typed
			ctx.push_raw(uint, id)
			for e in obj:
				write(e, ctx)
			return
		for e in obj:
			ctx.push(e)
	return ctor, True, _read or read, _write or write

def std_char(ctor, pre=lambda x:x, post=lambda x:x, _read=None, _write=None):
	def read(ctx):
		l = ctx.pull(uint)
		return post(bytearray(ctx._pull("B")[0] for _ in range(l)))
	def write(obj, ctx):
		obj = pre(obj)
		ctx.push_raw(uint, len(obj))
		for e in obj:
			ctx._push("B", e)
	return ctor, True, _read or read, _write or write


def guess_obj_attr(ctor):
	import dis
	attr = set()
	for func in filter(callable, ctor.__dict__.values()):
		on_self = False
		trust_self_name = func.__code__.co_varnames[0] == "self"
		for ins in dis.get_instructions(func):
			if on_self and ins.opcode == 95:
				attr.add(ins.argval)
			on_self = False
			if (ins.opcode == 124 and ins.arg == 0 or
				ins.opcode == 136 and ins.argval == "self" and trust_self_name):
				on_self = True
	return attr

def std_obj(ctor, _read=None, _write=None, guess=True):
	if guess:
		attr = guess_obj_attr(ctor)
		def read(ctx):
			obj = ctor.__new__(ctor)
			ctx.add_ref(obj)
			obj.__dict__ = {k:v for k,v in zip(attr, ctx.pull(tuple))}
			return obj
		def write(obj, ctx):
			ctx.push_raw(tuple, tuple(obj.__getattribute__(k) for k in attr))
	else:
		def read(ctx):
			obj = ctor.__new__(ctor)
			ctx.add_ref(obj)
			obj.__dict__ = ctx.pull(dict)
			return obj
		def write(obj, ctx):
			ctx.push_raw(dict, obj.__dict__)
	return ctor, True, _read or read, _write or write

def read_uint(ctx):
	obj = 0
	cond = True
	i = 0
	while cond:
		part, = ctx._pull("B")
		obj += (part>>1)<<i*7
		i += 1
		cond = part&1
	return obj
def write_uint(obj, ctx):
	cond = True
	while cond:
		part = obj&((1<<7)-1)
		print(part)
		obj >>= 7
		cond = obj>0
		ctx._push("B", part<<1|cond)

def read_int(ctx):
	obj, sign = get_flags(read_uint(ctx), 1)
	if sign:
		return -obj
	return obj
def write_int(obj, ctx):
	write_uint(add_flags(abs(obj), obj<0), ctx)

def read_range(ctx):
	return range(ctx.pull(int), ctx.pull(int), ctx.pull(int))
def write_range(obj, ctx):
	for part in (obj.start, obj.stop, obj.step):
		ctx.push_raw(int, part)

def write_complex(obj, ctx):
	ctx._push("2d", obj.real, obj.imag)

def write_none(obj, ctx):
	pass

def read_list(ctx):
	l, typed = get_flags(ctx.pull(uint), 1)
	obj = [None]*l
	ctx.add_ref(obj)
	if typed:
		id = ctx.pull(uint)
		sub_ctor, (id, read, write) = ctx.ctors.from_id(id)
		for i in range(l):
			obj[i] = read(ctx)
		return obj
	for i in range(l):
		e = ctx.pull_any(lazy_ref=True)
		obj[i] = e
		if isinstance(e, LazyRef):
			ctx.refs.watch(e.id, e.callback(obj, i))
	return obj

def read_dict(ctx):
	obj = dict()
	ctx.add_ref(obj)
	keys = ctx.pull(tuple)
	values = ctx.pull(tuple)
	for k, v in zip(keys, values):
		obj[k] = v
	return obj
def write_dict(obj, ctx):
	ctx.push_raw(tuple, obj.keys())
	ctx.push_raw(tuple, obj.values())


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
ctx.add_ctor(*std_atom(float, "d"))
ctx.add_ctor(*std_atom(complex, "2d", _write=write_complex))

ctx.add_ctor(uint,  False, read_uint,  write_uint)
ctx.add_ctor(int,   False, read_int,   write_int)
ctx.add_ctor(range, False, read_range, write_range)

ctx.add_ctor(*std_iter(list, _read=read_list))
ctx.add_ctor(*std_iter(tuple))
ctx.add_ctor(*std_iter(set))
ctx.add_ctor(*std_iter(frozenset))

ctx.add_ctor(*std_char(str, pre=str.encode, post=lambda x:x.decode()))
ctx.add_ctor(*std_char(bytes, post=bytes))
ctx.add_ctor(*std_char(bytearray))

ctx.add_ctor(dict, True, read_dict, write_dict)


class TestGuess:
	def __init__(self, a, b):
		self.long_name_a = a
		self.long_name_b = b
		self.long_name_c = a*b
		self.long_name_d = [(a, self) for _ in range(b)]
		self.long_name_e = {a:b, b:a, "self":self}
class TestNoGuess(TestGuess):
	pass

ctx.add_ctor(*std_obj(TestGuess))
ctx.add_ctor(*std_obj(TestNoGuess, guess=False))


test = 4
a=None
if test == 0:
	b=[None, 42, 3.14]
	a=(0,b,b,range(-1,10**10),"♟️", b"\xe2\x99\x9f\xef\xb8\x8f", bytearray(b"\xe2\x99\x9f\xef\xb8\x8f"))
	b.append(a)
elif test == 1:
	a={0:1, "a":0.1}
	b=(None, 42, 3.14)
	a[b]=a
elif test == 2:
	a={_:str(_) for _ in range(10)}
	#a[10]=None
elif test == 3:
	a=list(range(100))
	#a[3]="!"
elif test == 4:
	a=[TestNoGuess(2,5), "***", TestNoGuess(2,5)]

ctx.push(a)
ctx.clear()
x=ctx.pull_any()
