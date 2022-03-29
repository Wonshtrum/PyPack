from pypack import *


class TestGuess:
	def __init__(self, a, b):
		self.long_name_a = a
		self.long_name_b = b
		self.long_name_c = a*b
		self.long_name_d = [(a, self) for _ in range(b)]
		self.long_name_e = {a:b, b:a, "self":self}
class TestNoGuess(TestGuess):
	pass


ctx = Context()
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
	a=(TestGuess(2,5), TestNoGuess(2,5))

ctx.push(a)
ctx.clear()
x=ctx.pull_any()
