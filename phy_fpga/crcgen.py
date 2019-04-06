#!/usr/bin/env python3
# vim: ts=8 sw=8 noexpandtab
#
#   CRC code generator
#
#   Copyright (c) 2019 Michael Buesch <m@bues.ch>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License along
#   with this program; if not, write to the Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

from dataclasses import dataclass
import argparse
import sys


__all__ = [
	"CrcGen",
]


@dataclass
class Bit(object):
	name: str
	index: int

	@property
	def allBitsRecursive(self):
		yield self

	def optimize(self):
		pass

	def __eq__(self, other):
		return (isinstance(other, Bit) and
			self.name == other.name and
			self.index == other.index)

	def __ne__(self, other):
		return not self.__eq__(other)

	def py(self):
		if self.index:
			return "((%s >> %d) & 1)" % (self.name, self.index)
		return "(%s & 1)" % (self.name)

	def verilog(self):
		return "%s[%d]" % (self.name, self.index)

class XOR(object):
	def __init__(self, *items):
		assert(len(items) >= 2)
		self.__items = items

	@property
	def allBitsRecursive(self):
		for item in self.__items:
			yield from item.allBitsRecursive

	def optimize(self):
		newItems = []
		for item in self.__items:
			if item in newItems:
				continue
			if not isinstance(item, Bit):
				newItems.append(item)
				continue
			if sum(1 if (isinstance(i, Bit) and i == item) else 0
			       for i in self.__items) % 2:
				# We have an uneven count of this bit. Keep it once.
				newItems.append(item)
			else:
				# An even amount cancels out in XOR. Remove it.
				pass
		self.__items = newItems

	def py(self):
		string = " ^ ".join(item.py() for item in self.__items)
		return "(%s)" % string

	def verilog(self):
		string = " ^ ".join(item.verilog() for item in self.__items)
		return "(%s)" % string

class Word(object):
	def __init__(self, *bits, MSB=True):
		if len(bits) == 1 and isinstance(bits[0], (list, tuple)):
			bits = bits[0]
		if MSB:
			bits = reversed(bits)
		self.__items = list(bits)

	def __getitem__(self, index):
		return self.__items[index]

	def flatten(self):
		newItems = []
		for item in self.__items:
			if isinstance(item, XOR):
				newItems.append(XOR(*item.allBitsRecursive))
			else:
				newItems.append(bit)
		self.__items = newItems

	def optimize(self):
		for item in self.__items:
			item.optimize()

class CrcGen(object):
	def __init__(self, P=0x07, nrBits=8):
		assert(P & 1)
		self.__P = P
		self.__nrBits = nrBits

	def __gen(self, dataVarName, crcVarName):
		assert(self.__nrBits == 8) #TODO

		inData = Word([ Bit(dataVarName, i) for i in reversed(range(8)) ])
		inCrc  = Word([ Bit(crcVarName, i) for i in reversed(range(8)) ])

		base = Word([ XOR(inData[i], inCrc[i]) for i in reversed(range(8)) ])

		def p(a, b, bitNr):
			if a is None:
				return b
			if (self.__P >> bitNr) & 1:
				return XOR(a, b)
			return a

		prevWord = base
		for i in range(8):
			word = Word(p(prevWord[6], prevWord[7], 7),
				    p(prevWord[5], prevWord[7], 6),
				    p(prevWord[4], prevWord[7], 5),
				    p(prevWord[3], prevWord[7], 4),
				    p(prevWord[2], prevWord[7], 3),
				    p(prevWord[1], prevWord[7], 2),
				    p(prevWord[0], prevWord[7], 1),
				    p(None,        prevWord[7], 0))
			prevWord = word

		word.flatten()
		word.optimize()

		return word

	def __header(self):
		return ("THIS IS GENERATED CODE.\n"
			"This code is Public Domain.\n"
			"It can be used without any restrictions.\n")

	def genPython(self,
		      funcName="crc",
		      crcVarName="crc",
		      dataVarName="data"):
		word = self.__gen(dataVarName, crcVarName)
		ret = []
		ret.append("# vim: ts=8 sw=8 noexpandtab")
		ret.extend("# " + l for l in self.__header().splitlines())
		ret.append("")
		ret.append("# polynomial = 0x%X" % self.__P)
		ret.append("def %s(%s, %s):" % (funcName, crcVarName, dataVarName))
		for i, bit in enumerate(word):
			if i:
				operator = "|="
				shift = " << %d" % i
			else:
				operator = "="
				shift = ""
			ret.append("\tret %s (%s)%s" % (operator, bit.py(), shift))
		ret.append("\treturn ret")
		return "\n".join(ret)

	def genVerilog(self,
		       genFunction=True,
		       name="crc",
		       inDataName="inData",
		       inCrcName="inCrc",
		       outCrcName="outCrc"):
		word = self.__gen(inDataName, inCrcName)
		ret = []
		ret.append("// vim: ts=4 sw=4 noexpandtab")
		ret.extend("// " + l for l in self.__header().splitlines())
		ret.append("")
		if not genFunction:
			ret.append("`ifndef %s_V_" % name.upper())
			ret.append("`define %s_V_" % name.upper())
			ret.append("")
		ret.append("// polynomial = 0x%X" % self.__P)
		if genFunction:
			ret.append("function automatic [%d:0] %s;" % (self.__nrBits - 1, name))
		else:
			ret.append("module %s (" % name)
		ret.append("\tinput [%d:0] %s%s" % (self.__nrBits - 1, inCrcName,
						    ";" if genFunction else ","))
		ret.append("\tinput [%d:0] %s%s" % (self.__nrBits - 1, inDataName,
						    ";" if genFunction else ","))
		if genFunction:
			ret.append("begin")
		else:
			ret.append("\toutput [%d:0] %s," % (self.__nrBits - 1, outCrcName))
			ret.append(");")
		for i, bit in enumerate(word):
			ret.append("\t%s%s[%d] = %s;" % ("" if genFunction else "assign ",
							 name if genFunction else outCrcName,
							 i, bit.verilog()))
		if genFunction:
			ret.append("end")
			ret.append("endfunction")
		else:
			ret.append("endmodule")
			ret.append("")
			ret.append("`endif // %s_V_" % name.upper())
		return "\n".join(ret)

	def genC(self,
		 funcName="crc",
		 crcVarName="crc",
		 dataVarName="data",
		 static=False,
		 inline=False):
		word = self.__gen(dataVarName, crcVarName)
		cType = "uint%s_t" % self.__nrBits
		ret = []
		ret.append("// vim: ts=4 sw=4 noexpandtab")
		ret.extend("// " + l for l in self.__header().splitlines())
		ret.append("")
		ret.append("#ifndef %s_H_" % funcName.upper())
		ret.append("#define %s_H_" % funcName.upper())
		ret.append("")
		ret.append("#include <stdint.h>")
		ret.append("")
		ret.append("// polynomial = 0x%X" % self.__P)
		ret.append("%s%s%s %s(%s %s, uint8_t %s)" % ("static " if static else "",
							     "inline " if inline else "",
							     cType,
							     funcName,
							     cType,
							     crcVarName,
							     dataVarName))
		ret.append("{")
		ret.append("\t%s ret;" % cType)
		for i, bit in enumerate(word):
			if i:
				operator = "|="
				shift = " << %d" % i
			else:
				operator = "="
				shift = ""
			ret.append("\tret %s (%s)%s;" % (operator, bit.py(), shift))
		ret.append("\treturn ret;")
		ret.append("}")
		ret.append("")
		ret.append("#endif /* %s_H_ */" % funcName.upper())
		return "\n".join(ret)

if __name__ == "__main__":
	try:
		p = argparse.ArgumentParser()
		g = p.add_mutually_exclusive_group()
		g.add_argument("-p", "--python", action="store_true", help="Generate Python code")
		g.add_argument("-v", "--verilog-function", action="store_true", help="Generate Verilog function")
		g.add_argument("-m", "--verilog-module", action="store_true", help="Generate Verilog module")
		g.add_argument("-c", "--c", action="store_true", help="Generate C code")
		p.add_argument("-P", "--polynomial", type=int, default=0x07, help="CRC polynomial")
		p.add_argument("-B", "--nr-bits", type=int, choices=[8,], default=8, help="Number of bits")
		p.add_argument("-n", "--name", type=str, default="crc", help="Generated function/module name")
		p.add_argument("-D", "--data-param", type=str, default="data", help="Generated function/module data parameter name")
		p.add_argument("-C", "--crc-in-param", type=str, default="crcIn", help="Generated function/module crc input parameter name")
		p.add_argument("-O", "--crc-out-param", type=str, default="crcOut", help="Generated module crc output parameter name")
		p.add_argument("-S", "--static", action="store_true", help="Generated static C function")
		p.add_argument("-I", "--inline", action="store_true", help="Generated inline C function")
		p.add_argument("-T", "--test", action="store_true", help="Run unit tests")
		args = p.parse_args()

		if not (args.polynomial & 1) or args.polynomial > ((1 << args.nr_bits) - 1):
			raise Exception("Invalid polynomial.")
		gen = CrcGen(P=args.polynomial, nrBits=args.nr_bits)
		if args.test:
			pyCode = gen.genPython()
			exec(pyCode)

			def crc8_ref(crc, data, P=args.polynomial):
				data ^= crc
				for i in range(8):
					data = ((data << 1) ^ (P if (data & 0x80) else 0)) & 0xFF
				return data

			print("Testing...")
			for c in range(256):
				for d in range(256):
					if crc8_ref(c, d) != crc(c, d):
						raise Exception("Test failed.")
			print("done.")
		else:
			if args.python:
				print(gen.genPython(funcName=args.name,
						    crcVarName=args.crc_in_param,
						    dataVarName=args.data_param))
			elif args.verilog_function:
				print(gen.genVerilog(genFunction=True,
						     name=args.name,
						     inDataName=args.data_param,
						     inCrcName=args.crc_in_param,
						     outCrcName=args.crc_out_param))
			elif args.verilog_module:
				print(gen.genVerilog(genFunction=False,
						     name=args.name,
						     inDataName=args.data_param,
						     inCrcName=args.crc_in_param,
						     outCrcName=args.crc_out_param))
			elif args.c:
				print(gen.genC(funcName=args.name,
					       crcVarName=args.crc_in_param,
					       dataVarName=args.data_param,
					       static=args.static,
					       inline=args.inline))
		sys.exit(0)
	except Exception as e:
		print("ERROR: %s" % str(e), file=sys.stderr)
		sys.exit(1)