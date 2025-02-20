#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Is dit heel erg beun? Ja. Ja dat klopt.
import os, sys, math
import struct
import xml.sax, xml.sax.handler
import re

import numpy as np
from bs4 import BeautifulSoup as BSoup
import lxml
import cssutils
import logging
from matplotlib import colors

cssutils.log.setLevel(logging.CRITICAL)

def hex2col(c):
    if '#' in c:
        h = c.lstrip('#')
        if len(h) == 6:
            r = int(h[0:2], 16)
            g = int(h[2:4], 16)
            b = int(h[4:6], 16)
            c = (r, g, b)
        elif len(h) == 3:
            r = int(h[0], 16) / 15 * 255
            g = int(h[1], 16) / 15 * 255
            b = int(h[2], 16) / 15 * 255
            c = (r, g, b)
    else:
        c=colors.to_rgb(c)
        c= tuple(255*k for k in c)
    return c;

def hex_to_rgb(hex):
	rgb = []
	for i in (0, 2, 4):
		decimal = int(hex[i:i + 2], 16)
		rgb.append(decimal)

	return tuple(rgb)


def create_color_table(file):
	selectors = {}
	with open(file) as webpage:
		html = webpage.read()
		soup = BSoup(html, features="xml")
	for styles in soup.select('style'):
		css = styles.encode_contents()
		css = cssutils.parseString(css)
		for rule in css:
			if rule.type == rule.STYLE_RULE:
				style = rule.selectorText
				selectors[style] = {}
				for item in rule.style:
					propertyname = item.name
					value = item.value
					selectors[style][propertyname] = value

	color = {}
	color['0'] = (0, 0, 0)
	for i in selectors:
		if 'stroke' in selectors[i].keys():
			c = selectors[i]['stroke']
			c= hex2col(c)
			i = ''.join(i.split(".")[1:])
			color[i] = c
	masks = [m.start() for m in re.finditer('mask', str(soup))]
	if len(masks)>0:
		raise ValueError("Hey your file contains masks, but masks are not supported because it would take me another week or so to implement these.")
		#Actually implementing masks would require you to find the intersection points between your vectors and your mask. I.e. for each vector that enters the mask,
		#you need to move the end point of the vector to the intersection on the mask border. that sucks to do manually, so I will pass this on to you!
	stroke_ind = [m.start() for m in re.finditer('stroke=', str(soup))]
	stroke_ind += [m.start() for m in re.finditer('stroke =', str(soup))]
	l = []
	for i in stroke_ind:
		l.append(re.split('\"|\'', str(soup)[i:i + 16])[1])
	l = set(l)
	for i in l:
		color[i] = hex2col(i)

	color_dict=color
	return color_dict;  # colortable as dict


# color=[]
# if selectors['.cls-1']['stroke'].find("#")==-1):
#    color.append(selectors['.cls-1']['stroke'])


def class_to_color(classs):
	global color_dict
	if str(classs)=='-1':
		return -1;
	return list(color_dict.keys()).index(classs);
def pc(c):
	x,y = c
	if isinstance(x,int) and isinstance(y,int):
		return "(%d,%d)"%(x,y)
	else:
		return "(%.4f, %.4f)"%(x,y)

class RenderParameters(object):
	def __init__(self):
		# use 0.0 for a single frame
		self.time = 0.0
		# step size of galvo movement, in fractions of output size per sample (2=full width)
		self.on_speed = 2 / 30.0
		# same, but for "off" laser state
		self.off_speed = 2 / 20.0
		# bound for accurate bezier rendering (lower = better)
		self.flatness = 0.000002
		# output render size (max 32767)
		self.width = 32767
		self.height = 32767
		# angle below which a node is considered smooth
		self.curve_angle = 30.0
		# dwell time at the start of a path (samples)
		self.start_dwell = 3
		# dwell time on internal curved nodes (samples)
		self.curve_dwell = 0
		# dwell time on internal corner nodes (samples)
		self.corner_dwell = 4
		# dwell time at the end of a path (samples)
		self.end_dwell = 2
		# dwell time before switching the beam on, and after switching it off
		self.switch_on_dwell = 3
		self.switch_off_dwell = 3
		# how many pointer of overdraw for closed shapes
		self.closed_overdraw = 0
		self.closed_start_dwell = 4
		self.closed_end_dwell = 5
		# extra dwell for the first active pointer
		self.extra_first_dwell = 0
		# invert image (show inter-object trips)
		self.invert = False
		self.force = False

		self.reset_stats()
	def reset_stats(self):
		self.rate_divs = 0
		self.flatness_divs = 0
		self.objects = 0
		self.subpaths = 0
		self.points = 0
		self.points_line = 0
		self.points_trip = 0
		self.points_bezier = 0
		self.points_dwell_start = 0
		self.points_dwell_curve = 0
		self.points_dwell_corner = 0
		self.points_dwell_end = 0
		self.points_dwell_switch = 0
		self.points_on = 0

	def load(self, f):
		for line in open(f):
			line = line.replace("\n","").strip()
			if line=="":
				continue
			var, val = line.split("=",1)
			var = var.strip()
			val = val.strip()
			self.__setattr__(var, eval(val))


class PathLine(object):
	def __init__(self, start, end, on=True,color=3):
		self.start = start
		self.end = end
		self.on = on
		self.color=color
	def copy(self):
		return PathLine(self.start, self.end,self.on,self.color)
	def transform(self, func):
		self.start = func(self.start)
		self.end = func(self.end)
	def render(self, params):
		dx = self.end[0] - self.start[0]
		dy = self.end[1] - self.start[1]
		length = math.sqrt(dx**2 + dy**2)
		if self.on:
			steps = int(length / params.on_speed) + 1
		else:
			steps = int(length / params.off_speed) + 1
		dx /= steps
		dy /= steps
		out = []
		for i in range(1, steps+1):
			x = self.start[0] + i * dx
			y = self.start[1] + i * dy
			out.append(LaserSample((int(x*params.width),int(y*params.height)), self.on, self.color))
			if self.on:
				params.points_line += 1
			else:
				params.points_trip += 1
		return out
	def reverse(self):
		return PathLine(self.end, self.start, self.on,self.color)
	def scp(self):
		return self.end
	def ecp(self):
		return self.start
	def showinfo(self, tr=''):
		print(tr+'Line( %s %s )'%(pc(self.start),pc(self.end)))

class PathBezier3(object):
	def __init__(self, start, cp, end,color):
		self.start = start
		self.end = end
		self.cp = cp
		self.color = color
	def copy(self):
		return PathBezier3(self.start, self.cp, self.end,self.color)
	def transform(self, func):
		self.start = func(self.start)
		self.cp = func(self.cp)
		self.end = func(self.end)
	def render(self, params):
		# just use PathBezier4, meh
		sx,sy = self.start
		cx,cy = self.cp
		ex,ey = self.end

		c1x = (1.0/3) * cx + (2.0/3) * sx
		c1y = (1.0/3) * cy + (2.0/3) * sy
		c2x = (1.0/3) * cx + (2.0/3) * ex
		c2y = (1.0/3) * cy + (2.0/3) * ey
		return PathBezier4(self.start, (c1x,c1y), (c2x,c2y), self.end,self.color).render(params)
	def reverse(self):
		return PathBezier3(self.end, self.cp, self.start,self.color)
	def scp(self):
		return self.cp
	def ecp(self):
		return self.cp
	def showinfo(self, tr=''):
		print(tr+'Bezier( %s %s %s )'%(pc(self.start),pc(self.cp),pc(self.end)))

class PathBezier4(object):
	def __init__(self, start, cp1, cp2, end,color):
		self.start = start
		self.end = end
		self.cp1 = cp1
		self.cp2 = cp2
		self.color=color
	def copy(self):
		return PathBezier4(self.start, self.cp1, self.cp2, self.end,self.color)
	def transform(self, func):
		self.start = func(self.start)
		self.cp1 = func(self.cp1)
		self.cp2 = func(self.cp2)
		self.end = func(self.end)

	def render(self, params):
		x0,y0 = self.start
		x1,y1 = self.cp1
		x2,y2 = self.cp2
		x3,y3 = self.end
		dx = x3-x0
		dy = y3-y0
		length = math.sqrt((dx**2) + (dy**2))
		subdivide = False
		if length > params.on_speed:
			subdivide = True
			params.rate_divs += 1
		else:
			ux = (3.0*x1 - 2.0*x0 - x3)**2
			uy = (3.0*y1 - 2.0*y0 - y3)**2
			vx = (3.0*x2 - 2.0*x3 - x0)**2
			vy = (3.0*y2 - 2.0*y3 - y0)**2
			if ux < vx:
				ux = vx
			if uy < vy:
				uy = vy
			if (ux+uy) > params.flatness:
				subdivide = True
				params.flatness_divs += 1
		if subdivide:
			# de Casteljau at t=0.5
			mcx = (x1 + x2) * 0.5
			mcy = (y1 + y2) * 0.5
			ax1 = (x0 + x1) * 0.5
			ay1 = (y0 + y1) * 0.5
			ax2 = (ax1 + mcx) * 0.5
			ay2 = (ay1 + mcy) * 0.5
			bx2 = (x2 + x3) * 0.5
			by2 = (y2 + y3) * 0.5
			bx1 = (bx2 + mcx) * 0.5
			by1 = (by2 + mcy) * 0.5
			xm = (ax2 + bx1) * 0.5
			ym = (ay2 + by1) * 0.5
			curve1 = PathBezier4((x0,y0),(ax1,ay1),(ax2,ay2),(xm,ym),self.color)
			curve2 = PathBezier4((xm,ym),(bx1,by1),(bx2,by2),(x3,y3),self.color)
			return curve1.render(params) + curve2.render(params)
		else:
			params.points_bezier += 1
			return [LaserSample((int(x3*params.width),int(y3*params.height)),True,self.color)]
	def reverse(self):
		return PathBezier4(self.end, self.cp2, self.cp1, self.start,self.color)
	def scp(self):
		if self.cp1 != self.start:
			return self.cp1
		elif self.cp2 != self.start:
			return self.cp2
		else:
			return self.end
	def ecp(self):
		if self.cp2 != self.end:
			return self.cp2
		elif self.cp1 != self.end:
			return self.cp1
		else:
			return self.start
	def showinfo(self, tr=''):
		print(tr+'Bezier( %s %s %s %s )'%(pc(self.start),pc(self.cp1),pc(self.cp2),pc(self.end)))

class LaserPath(object):
	def __init__(self):
		self.segments = []
	def add(self, seg,color):
		self.segments.append(seg)
	def transform(self, func):
		for i in self.segments:
			i.transform(func)
	def render(self, params):
		is_closed = self.segments[0].start == self.segments[-1].end
		sx,sy = self.segments[0].start
		col=self.segments[0].color
		out = []
		if is_closed:
			out += [LaserSample((int(sx*params.width),int(sy*params.height)),True,col)] * params.closed_start_dwell
		else:
			out += [LaserSample((int(sx*params.width),int(sy*params.height)),True,col)] * params.start_dwell
		params.points_dwell_start += params.start_dwell
		for i,s in enumerate(self.segments):
			params.subpaths += 1
			out += s.render(params)
			ex,ey = s.end
			end_render = [LaserSample((int(ex*params.width),int(ey*params.height)),True,s.color)]
			if i != len(self.segments)-1:
				ecx,ecy = s.ecp()
				sx,sy = self.segments[i+1].start
				scx,scy = self.segments[i+1].scp()

				dex,dey = ecx-ex,ecy-ey
				dsx,dsy = sx-scx,sy-scy

				dot = dex*dsx + dey*dsy
				lens = math.sqrt(dex**2 + dey**2) * math.sqrt(dsx**2 + dsy**2)
				if lens == 0:
					# bail
					out += end_render * params.corner_dwell
					params.points_dwell_corner += params.corner_dwell
				else:
					dot /= lens
					curve_angle = math.cos(params.curve_angle*(math.pi/180.0))
					if dot > curve_angle:
						out += end_render * params.curve_dwell
						params.points_dwell_curve += params.curve_dwell
					else:
						out += end_render * params.corner_dwell
						params.points_dwell_corner += params.corner_dwell
			elif is_closed:
				overdraw = out[:params.closed_overdraw]
				out += overdraw
				out += [out[-1]] * params.closed_end_dwell
				params.points_dwell_end += params.closed_end_dwell
			else:
				out += end_render * params.end_dwell
				params.points_dwell_end += params.end_dwell
		return out
	def startpos(self):
		return self.segments[0].start
	def endpos(self):
		return self.segments[-1].end
	def reverse(self):
		lp = LaserPath()
		lp.segments = [x.reverse() for x in self.segments[::-1]]
		return lp
	def showinfo(self, tr=''):
		print(tr+'LaserPath:')
		for i in self.segments:
			i.showinfo(tr+' ')

class ClassFrame(object):
	def __init__(self,classs=None):
		self.objects=[]
		self.classs=classs
	def add(self, obj):
		self.objects.append(obj)
	def transform(self, func):
		for i in self.objects:
			i.transform(func)



class LaserFrame(object):
	def __init__(self):
		self.objects = []
	def add(self, obj):
		self.objects.append(obj)
	def transform(self, func):
		for i in self.objects:
			i.transform(func)
	def render(self, params):

		if not self.objects:
			return []
		out = []
		for n,i in enumerate(self.objects):
			params.objects += 1
			out += i.render(params)
			cpos = out[-1].coord[0] / params.width, out[-1].coord[1] / params.height
			npos = self.objects[(n+1) % len(self.objects)].startpos()
			trip = [LaserSample((int(cpos[0]*params.width),int(cpos[1]*params.height)),True,i.segments[-1].color)] * params.switch_on_dwell
			trip += PathLine(cpos,npos,False,-1).render(params)
			trip += [LaserSample((int(npos[0]*params.width),int(npos[1]*params.height)),True,i.segments[-1].color)] * params.switch_off_dwell
			params.points_dwell_switch += params.switch_on_dwell + params.switch_off_dwell
			for s in trip:
				s.on = False
			out += trip
		params.points = len(out)
		params.points_on = sum([int(s.on) for s in out])
		return out


	def custom_sort(self):
		oobj = []
		cx, cy = 0, 0
		while self.objects:
			best = 99999
			besti = 0
			bestr = False
			for i, o in enumerate(self.objects):
				x, y = o.startpos()
				d = (x - cx) ** 2 + (y - cy) ** 2
				if d < best:
					best = d
					besti = i
				x, y = o.endpos()
				d = (x - cx) ** 2 + (y - cy) ** 2
				if d < best:
					best = d
					besti = i
					bestr = True
			obj = self.objects.pop(besti)
			if bestr:
				obj = obj.reverse()
			oobj.append(obj)
			cx, cy = obj.endpos()
		self.objects = oobj

	def sort(self):
		oobj = []
		cx,cy = 0,0
		while self.objects:
			best = 99999
			besti = 0
			bestr = False
			for i,o in enumerate(self.objects):
				x,y = o.startpos()
				d = (x-cx)**2 + (y-cy)**2
				if d < best:
					best = d
					besti = i
				x,y = o.endpos()
				d = (x-cx)**2 + (y-cy)**2
				if d < best:
					best = d
					besti = i
					bestr = True
			obj = self.objects.pop(besti)
			if bestr:
				obj = obj.reverse()
			oobj.append(obj)
			cx,cy = obj.endpos()
		self.objects = oobj
	def showinfo(self, tr=''):
		print(tr+'LaserFrame:')
		for i in self.objects:
			i.showinfo(tr+' ')

class LaserSample(object):
	def __init__(self, coord, on=True, color=0):
		self.coord = coord
		self.on = on
		self.color=color
	def __str__(self):
		return "[%d] %d,%d"%(int(self.on),self.coord[0],self.coord[1])
	def __repr__(self):
		return "LaserSample((%d,%d),%r,%d)"%(self.coord[0],self.coord[1],self.on,self.color)

class SVGPath(object):
	def __init__(self, data=None,color=334, classs=None):
		self.subpaths = []
		self.color=color
		if data:
			self.parse(data)

	def poptok(self):
		if not self.tokens:
			raise ValueError("Expected token but got end of path data")
		return self.tokens.pop(0)
	def peektok(self):
		if not self.tokens:
			raise ValueError("Expected token but got end of path data")
		return self.tokens[0]
	def popnum(self):
		tok = self.tokens.pop(0)
		try:
			return float(tok)
		except ValueError:
			raise ValueError("Invalid SVG path numerical token: %s"%tok)
	def isnum(self):
		if not self.tokens:
			return False # no more tokens is considered a non-number
		try:
			float(self.peektok())
		except ValueError:
			return False
		return True
	def popcoord(self,rel=False, cur=None):
		x = self.popnum()
		if self.peektok() == ',':
			self.poptok()
		y = self.popnum()
		if rel:
			x += cur[0]
			y += cur[1]
		return x,y
	def reflect(self, center, point):
		cx,cy = center
		px,py = point
		return (2*cx-px, 2*cy-py)

	def angle(self, u, v):
		# calculate the angle between two vectors
		ux, uy = u
		vx, vy = v
		dot = ux*vx + uy*vy
		ul = math.sqrt(ux**2 + uy**2)
		vl = math.sqrt(vx**2 + vy**2)
		a = math.acos(dot/(ul*vl))
		return math.copysign(a, ux*vy - uy*vx)
	def arc_eval(self, cx, cy, rx, ry, phi, w):
		# evaluate a point on an arc
		x = rx * math.cos(w)
		y = ry * math.sin(w)
		x, y = x*math.cos(phi) - y*math.sin(phi), math.sin(phi)*x + math.cos(phi)*y
		x += cx
		y += cy
		return (x,y)
	def arc_deriv(self, rx, ry, phi, w):
		# evaluate the derivative of an arc
		x = -rx * math.sin(w)
		y = ry * math.cos(w)
		x, y = x*math.cos(phi) - y*math.sin(phi), math.sin(phi)*x + math.cos(phi)*y
		return (x,y)
	def arc_to_beziers(self, cx, cy, rx, ry, phi, w1, dw):
		# convert an SVG arc to 1-4 bezier segments
		segcnt = min(4,int(abs(dw) / (math.pi/2) - 0.00000001) + 1)
		beziers = []
		for i in range(segcnt):
			sw1 = w1 + dw / segcnt * i
			sdw = dw / segcnt
			p0 = self.arc_eval(cx, cy, rx, ry, phi, sw1)
			p3 = self.arc_eval(cx, cy, rx, ry, phi, sw1+sdw)
			a = math.sin(sdw)*(math.sqrt(4+3*math.tan(sdw/2)**2)-1)/3
			d1 = self.arc_deriv(rx, ry, phi, sw1)
			d2 = self.arc_deriv(rx, ry, phi, sw1+sdw)
			p1 = p0[0] + a*d1[0], p0[1] + a*d1[1]
			p2 = p3[0] - a*d2[0], p3[1] - a*d2[1]
			beziers.append(PathBezier4(p0, p1, p2, p3,self.color))
		return beziers
	def svg_arc_to_beziers(self, start, end, rx, ry, phi, fa, fs):
		# first convert endpoint format to center-and-radii format
		rx, ry = abs(rx), abs(ry)
		phi = phi % (2*math.pi)

		x1, y1 = start
		x2, y2 = end
		x1p = (x1 - x2) / 2
		y1p = (y1 - y2) / 2
		psin = math.sin(phi)
		pcos = math.cos(phi)
		x1p, y1p = pcos*x1p + psin*y1p, -psin*x1p + pcos*y1p
		foo = x1p**2 / rx**2 + y1p**2 / ry**2
		sr = ((rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2) /
					(rx**2 * y1p**2 + ry**2 * x1p**2))
		if foo > 1 or sr < 0:
			#print "fixup!",foo,sr
			rx = math.sqrt(foo)*rx
			ry = math.sqrt(foo)*ry
			sr = 0

		srt = math.sqrt(sr)
		if fa == fs:
			srt = -srt
		cxp, cyp = srt * rx * y1p / ry, -srt * ry * x1p / rx
		cx, cy = pcos*cxp + -psin*cyp, psin*cxp + pcos*cyp
		cx, cy = cx + (x1+x2)/2, cy + (y1+y2)/2

		va = ((x1p - cxp)/rx, (y1p - cyp)/ry)
		vb = ((-x1p - cxp)/rx, (-y1p - cyp)/ry)
		w1 = self.angle((1,0), va)
		dw = self.angle(va, vb) % (2*math.pi)
		if not fs:
			dw -= 2*math.pi

		# then do the actual approximation
		return self.arc_to_beziers(cx, cy, rx, ry, phi, w1, dw)

	def parse(self, data):
		ds = re.split(r"[ \r\n\t]*([-+]?\d+\.\d+[eE][+-]?\d+|[-+]?\d+\.\d+|[-+]?\.\d+[eE][+-]?\d+|[-+]?\.\d+|[-+]?\d+\.?[eE][+-]?\d+|[-+]?\d+\.?|[MmZzLlHhVvCcSsQqTtAa])[, \r\n\t]*", data)
		tokens = ds[1::2]
		if any(ds[::2]) or not all(ds[1::2]):
			raise ValueError("Invalid SVG path expression: %r"%data)
		self.tokens = tokens

		cur = (0,0)
		curcpc = (0,0)
		curcpq = (0,0)
		sp_start = (0,0)
		in_path = False
		cmd = None
		subpath = LaserPath()
		while tokens:
			if self.isnum() and cmd in "MmLlHhVvCcSsQqTtAa":
				pass
			elif self.peektok() in "MmZzLlHhVvCcSsQqTtAa":
				cmd = tokens.pop(0)
			else:
				raise ValueError("Invalid SVG path token %s"%tok)

			rel = cmd.upper() != cmd
			ucmd = cmd.upper()

			if not in_path and ucmd != 'M' :
				raise ValueErorr("SVG path segment must begin with 'm' command, not '%s'"%cmd)

			if ucmd == 'M':
				sp_start = self.popcoord(rel, cur)
				if subpath.segments:
					self.subpaths.append(subpath)
				subpath = LaserPath()
				cmd = 'Ll'[rel]
				cur = curcpc = curcpq = sp_start
				in_path = True
			elif ucmd == 'Z':
				#print(sp_start, cur)
				if (sp_start[0] - cur[0]) > 0.0000001 or (sp_start[1] - cur[1]) > 0.0000001:
					subpath.add(PathLine(cur, sp_start,True,self.color),self.color)
				cur = curcpc = curcpq = sp_start
				subpath.segments[-1].end = subpath.segments[0].start
				in_path = False
			elif ucmd == 'L':
				end = self.popcoord(rel, cur)
				subpath.add(PathLine(cur, end,True,self.color),self.color)
				cur = curcpc = curcpq = end
			elif ucmd == 'H':
				ex = self.popnum()
				if rel:
					ex += cur[0]
				end = ex,cur[1]
				subpath.add(PathLine(cur, end, True,self.color),self.color)
				cur = curcpc = curcpq = end
			elif ucmd == 'V':
				ey = self.popnum()
				if rel:
					ey += cur[1]
				end = cur[0],ey
				subpath.add(PathLine(cur, end, True, self.color),self.color)
				cur = curcpc = curcpq = end
			elif ucmd in 'CS':
				if ucmd == 'S':
					c1 = self.reflect(cur,curcpc)
				else:
					c1 = self.popcoord(rel, cur)
				c2 = curcpc = self.popcoord(rel, cur)
				end = self.popcoord(rel, cur)
				subpath.add(PathBezier4(cur, c1, c2, end, self.color),self.color)
				cur = curcpq = end
			elif ucmd in 'QT':
				if ucmd == 'T':
					cp = curcpq = self.reflect(cur,curcpq)
				else:
					cp = curcpq = self.popcoord(rel, cur)
				end = self.popcoord(rel, cur)
				subpath.add(PathBezier3(cur, cp, end,self.color),self.color)
				cur = curcpc = end
			elif ucmd == 'A':
				rx, ry = self.popcoord()
				phi = self.popnum() / 180.0 * math.pi
				fa = self.popnum() != 0
				fs = self.popnum() != 0
				end = self.popcoord(rel, cur)

				if cur == end:
					cur = curcpc = curcpq = end
					continue
				if rx == 0 or ry == 0:
					subpath.add(PathLine(cur, end, True, self.color),self.color)
					cur = curcpc = curcpq = end
					continue

				subpath.segments += self.svg_arc_to_beziers(cur, end, rx, ry, phi, fa, fs)
				cur = curcpc = curcpq = end

		if subpath.segments:
			self.subpaths.append(subpath)

class SVGPolyline(SVGPath):
	def __init__(self, data=None, close=False, color=223):
		self.subpaths = []
		self.color=color
		if data:
			self.parse(data, close)
	def parse(self, data, close=False):
		ds = re.split(r"[ \r\n\t]*([-+]?\d+\.\d+[eE][+-]?\d+|[-+]?\d+\.\d+|[-+]?\.\d+[eE][+-]?\d+|[-+]?\.\d+|[-+]?\d+\.?[eE][+-]?\d+|[-+]?\d+\.?)[, \r\n\t]*", data)
		tokens = ds[1::2]
		if any(ds[::2]) or not all(ds[1::2]):
			raise ValueError("Invalid SVG path expression: %r"%data)

		self.tokens = tokens
		cur = None
		first = None
		subpath = LaserPath()
		while tokens:
			pt = self.popcoord()
			if first is None:
				first = pt
			if cur is not None:
				subpath.add(PathLine(cur, pt, True,self.color),self.color)
			cur = pt
		if close:
			subpath.add(PathLine(cur, first, True, self.color),self.color)
		self.subpaths.append(subpath)

class SVGReader(xml.sax.handler.ContentHandler):
	def process_attributes(self,attrs):
		global color_dict
		#print(color_dict)
		#check_class_frame(classs)
		color = 0;
		stroke = hex2col("#A0A000")
		if 'class' in attrs.keys():
			classs=attrs['class']
			#color = class_to_color('.'+attrs['class'])
		elif 'id' in attrs.keys():
			classs = attrs['id']
		elif 'stroke' in attrs.keys():
			classs = attrs['stroke']
		elif 'xlink:href' in attrs.keys():
			classs = attrs['xlink:href'].replace("#","")
		if 'stroke' in attrs.keys():
			stroke = hex2col(attrs['stroke'])

		for i in range(self.id_index+1):
			self.id_stack[i].append(classs)
		#if self.id_index>1:
		#	print("aaaa")
		frame=self.check_class_frame(classs)
		if not (classs in color_dict):
			color_dict[classs] = stroke
			color=list(color_dict.keys()).index(classs)
		else:
			color = list(color_dict.keys()).index(classs)#color_dict[classs] #oorrr... should this be the other way around?
		return color,frame;
			#color = class_to_color('.' + attrs['class'])

	def doctype(self, name, pubid, system):
		print(name,pubid,system)
	def startDocument(self):
		self.frame = LaserFrame()
		self.matrix_stack = [(1,0,0,1,0,0)]
		self.id_stack = [[]] #list of lsits
		self.style_stack = []
		self.id_index=0;
		self.defsdepth = 0
		self.classframes=[]
	def endDocument(self):
		self.frame.transform(self.tc)
	def startElement(self, name, attrs):
		if name == "svg":
			self.dx = self.dy = 0
			if 'viewBox' in attrs.keys():
				self.dx, self.dy, self.width, self.height = map(float, attrs['viewBox'].split())
			else:
				ws = attrs['width']
				hs = attrs['height']
				for r in ('px','pt','mm','in','cm','%'):
					hs = hs.replace(r,"")
					ws = ws.replace(r,"")
				self.width = float(ws)
				self.height = float(hs)
		elif name == "path":
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			if self.isvisible(attrs):
				color = -20
				color,frame = self.process_attributes(attrs)
				self.addPath(attrs['d'],color,frame=frame)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name in ("polyline","polygon"):
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			if self.defsdepth == 0 and self.isvisible(attrs):
				color = -20
				color,frame = self.process_attributes(attrs)
				self.addPolyline(attrs['points'],color,frame=frame)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name == "line":
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			if self.defsdepth == 0 and self.isvisible(attrs):
				x1, y1, x2, y2 = [float(attrs[x]) for x in ('x1','y1','x2','y2')]
				color=-20
				color,frame = self.process_attributes(attrs)
				self.addLine(x1, y1, x2, y2,color=color,frame=frame)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name == "rect":
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			if self.defsdepth == 0 and self.isvisible(attrs):
				x1, y1, w, h = [float(attrs[x]) for x in ('x','y','width','height')]
				color = -20
				color,frame = self.process_attributes(attrs)
				self.addRect(x1, y1, x1+w, y1+h,color=color,frame=frame)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name == "circle":
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			if self.defsdepth == 0 and self.isvisible(attrs):
				cx, cy, r = [float(attrs[x]) for x in ('cx','cy','r')]
				color = -20
				color,frame = self.process_attributes(attrs)
				self.addCircle(cx, cy, r,color=color,frame=frame)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name == "ellipse":
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			if self.defsdepth == 0 and self.isvisible(attrs):
				cx, cy, rx, ry = [float(attrs[x]) for x in ('cx','cy','rx','ry')]
				color = -20
				color,frame = self.process_attributes(attrs)
				self.addEllipse(cx, cy, rx, ry,color=color,frame=frame)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name == "use":
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			self.process_attributes(attrs)
			if 'transform' in attrs.keys():
				self.popmatrix()
		elif name == 'g':
			if 'transform' in attrs.keys():
				self.transform(attrs['transform'])
			else:
				self.pushmatrix((1,0,0,1,0,0))
			if 'style' in attrs.keys():
				self.style_stack.append(attrs['style'])
			else:
				self.style_stack.append("")
		elif name in ('defs','clipPath'):
			self.defsdepth += 1
	def endElement(self, name):
		if name == 'g':
			#print(len(self.matrix_stack))
			#print(self.matrix_stack)
			#Apply transform to all recorded items;


			self.popmatrix() #REmoving this is a super temporary fix to get Adobe transforms working lol
			self.style_stack.pop()

		elif name in ('defs','clipPath'):
			self.defsdepth -= 1
		if name =='svg':
			#print("Hey Ho")
			for i in self.classframes:
				for j in i.objects:
					self.frame.add(j)
	def mmul(self, m1, m2):
		a1,b1,c1,d1,e1,f1 = m1
		a2,b2,c2,d2,e2,f2 = m2
		a3 = a1 * a2 + c1 * b2
		b3 = b1 * a2 + d1 * b2
		c3 = a1 * c2 + c1 * d2
		d3 = b1 * c2 + d1 * d2
		e3 = a1 * e2 + c1 * f2 + e1
		f3 = b1 * e2 + d1 * f2 + f1
		return (a3,b3,c3,d3,e3,f3)
	def check_class_frame(self,classs):
		#ClassFrame
		for i in self.classframes: #Search for class in classframes
			if i.classs==classs:
				return i; #We found it, so return it
		a=ClassFrame(classs) #otherwise, create one, add it to the classframes array, and return it.
		self.classframes.append(a)
		return a
	def pushmatrix(self, m):
		#print("Pushmatrix")
		self.id_index+=1
		self.id_stack.append([])
		new_mat = m# self.mmul(self.matrix_stack[-1], m)
		self.matrix_stack.append(new_mat)
	def popmatrix(self):
		for j in self.id_stack[self.id_index]:
			for i in self.classframes:
				if i.classs == j:
					i.transform(self.ts)  # apply TC transform
			# print("Applying transform:" + str(i.classs))
		self.id_stack.pop()
		self.id_index-=1;
		self.matrix_stack.pop()
	def tc(self,coord):
		vw = vh = max(self.width, self.height) / 2.0
		x,y = coord
		x -= self.width / 2.0 + self.dx
		y -= self.height / 2.0 + self.dy
		# if vw!=960:
		# 	print(vw)
		# 	print("")
		x = x / vw
		y = y / vh
		return (x,y)
	def ts(self,coord):
		a,b,c,d,e,f = self.matrix_stack[-1]
		x,y = coord
		nx = a*x + c*y + e
		ny = b*x + d*y + f
		return (nx,ny)
	def transform(self, data):
		ds = re.split(r"[ \r\n\t]*([a-z]+\([^)]+\)|,)[ \r\n\t]*", data)
		tokens = []
		for v in ds:
			if v in ', \t':
				continue
			if v == '':
				continue
			if not re.match(r"[a-z]+\([^)]+\)", v):
				raise ValueError("Invalid SVG transform expression: %r (%r)"%(data,v))
			tokens.append(v)
		transforms = tokens

		mat = (1,0,0,1,0,0)
		for t in transforms:
			name,rest = t.split("(")
			if rest[-1] != ")":
				raise ValueError("Invalid SVG transform expression: %r (%r)"%(data,rest))
			args = list(map(float,re.split(r',',rest[:-1])))
			if name == 'matrix':
				mat = self.mmul(mat, args)
			elif name == 'translate':
				tx,ty = args
				mat = self.mmul(mat, (1,0,0,1,tx,ty))
			elif name == 'scale':
				if len(args) == 1:
					sx,sy = args[0],args[0]
				else:
					sx,sy = args
				mat = self.mmul(mat, (sx,0,0,sy,0,0))
			elif name == 'rotate':
				a = args[0] / 180.0 * math.pi
				if len(args) == 3:
					cx,cy = args[1:]
					mat = self.mmul(mat, (1,0,0,1,cx,cy))
				cos = math.cos(a)
				sin = math.sin(a)
				mat = self.mmul(mat, (cos,sin,-sin,cos,0,0))
				if len(args) == 3:
					mat = self.mmul(mat, (1,0,0,1,-cx,-cy))
			elif name == 'skewX':
				a = args[0] / 180.0 * math.pi
				mat = self.mmul(mat, (1,0,math.tan(a),1,0,0))
			elif name == 'skewY':
				a = args[0] / 180.0 * math.pi
				mat = self.mmul(mat, (1,math.tan(a),0,1,0,0))
		self.pushmatrix(mat)
	def addPath(self, data,color,frame):
		p = SVGPath(data,color)
		for path in p.subpaths:
			path.transform(self.ts)
			frame.add(path)
	def addPolyline(self, data,color,frame,close=False):
		q = data.split(" ")
		if (q[0]!=q[-2]): #Open path, but I think all paths should be closed so lets close it.
			m=""
			for i in q:
				m = m + str(i + " ")
			m = m + str(q[0] + " ")
			data=m
			#print(m)
		p = SVGPolyline(data, close,color)
		for path in p.subpaths:
			path.transform(self.ts)
			frame.add(path)
	def addLine(self, x1, y1, x2, y2, color,frame):
		path = LaserPath()
		path.add(PathLine((x1,y1), (x2,y2),True,color=color),color=color)
		path.transform(self.ts)
		frame.add(path)
	def addRect(self, x1, y1, x2, y2,color,frame):
		path = LaserPath()
		path.add(PathLine((x1,y1), (x2,y1),True,color),color)
		path.add(PathLine((x2,y1), (x2,y2),True,color),color)
		path.add(PathLine((x2,y2), (x1,y2),True,color),color)
		path.add(PathLine((x1,y2), (x1,y1),True,color),color)
		path.transform(self.ts)
		frame.add(path)
	def addCircle(self, cx, cy, r,color,frame):
		cp = 0.55228475 * r
		path = LaserPath()
		path.add(PathBezier4((cx,cy-r), (cx+cp,cy-r), (cx+r,cy-cp), (cx+r,cy),True,color),color)
		path.add(PathBezier4((cx+r,cy), (cx+r,cy+cp), (cx+cp,cy+r), (cx,cy+r),True,color),color)
		path.add(PathBezier4((cx,cy+r), (cx-cp,cy+r), (cx-r,cy+cp), (cx-r,cy),True,color),color)
		path.add(PathBezier4((cx-r,cy), (cx-r,cy-cp), (cx-cp,cy-r), (cx,cy-r)),True,color,color)
		path.transform(self.ts)
		frame.add(path)
	def addEllipse(self, cx, cy, rx, ry,color,frame):
		cpx = 0.55228475 * rx
		cpy = 0.55228475 * ry
		path = LaserPath()
		path.add(PathBezier4((cx,cy-ry), (cx+cpx,cy-ry), (cx+rx,cy-cpy), (cx+rx,cy),True,color),color)
		path.add(PathBezier4((cx+rx,cy), (cx+rx,cy+cpy), (cx+cpx,cy+ry), (cx,cy+ry),True,color),color)
		path.add(PathBezier4((cx,cy+ry), (cx-cpx,cy+ry), (cx-rx,cy+cpy), (cx-rx,cy),True,color),color)
		path.add(PathBezier4((cx-rx,cy), (cx-rx,cy-cpy), (cx-cpx,cy-ry), (cx,cy-ry),True,color),color)
		path.transform(self.ts)
		frame.add(path)
	def isvisible(self, attrs):
		# skip elements with no stroke or fill
		# hacky but gets rid of some gunk
		style = ' '.join(self.style_stack)
		if 'style' in attrs.keys():
			style += " %s"%attrs['style']
		if 'fill' in attrs.keys() and attrs['fill'] != "none":
			return True
		style = re.sub(r'fill:\s*none\s*(;?)','', style)
		style = re.sub(r'stroke:\s*none\s*(;?)','', style)
		if 'stroke' not in style and re.match(r'fill:\s*none\s',style):
			return False
		if "stroke" in attrs:
			if attrs['stroke'] == "none":
				return False
		if re.match(r'display:\s*none', style):
			return False
		return True

def load_svg(path):
	global color_dict
	color_dict=create_color_table(path)
	handler = SVGReader()
	parser = xml.sax.make_parser()
	parser.setContentHandler(handler)
	parser.setFeature(xml.sax.handler.feature_external_ges, False)
	parser.parse(path)
	return handler.frame
def write_color(fout):
	global color_dict
	# First write color frame
	if '' in color_dict:
		color_dict.pop('')
	colors = list(color_dict.values())
	clrs = []
	q = 0;

	dout = b""
	hdr = struct.pack(">4s3xB8s8sHHHBx", b"ILDA", 2, b"svg2ilda", b"LANCo", len(color_dict), 0, 0, 0)
	for color in colors:
		dout += struct.pack(">BBB", int(color[0]), int(color[1]), int(color[2]))

	fout.write(hdr)
	fout.write(dout)


def write_ild(fout,current_frame, params, rframe, path, center=True):
	global number_of_frames, offx, offy
	min_x = min_y = max_x = max_y = None
	for i,sample in enumerate(rframe):
		x,y = sample.coord
		if min_x is None or min_x > x:
			min_x = x
		if min_y is None or min_y > y:
			min_y = y
		if max_x is None or max_x < x:
			max_x = x
		if max_y is None or max_y < y:
			max_y = y

	for i,sample in enumerate(rframe):
		if sample.on:
			rframe = rframe[:i] + [sample]*params.extra_first_dwell + rframe[i+1:]
			break
	samples=i #number of pojnts
	if len(rframe) == 0:
		raise ValueError("No points rendered")

	if current_frame==0:
		# center image
		if center:
			offx = -(min_x + max_x)/2
			offy = -(min_y + max_y)/2
			width = max_x - min_x
			height = max_y - min_y
		else:
			offx = 0
			offy = 0
			width = 2*max(abs(min_x), abs(max_x))
			height = 2*max(abs(min_y), abs(max_y))
	else:
		width = 2 * max(abs(min_x), abs(max_x))
		height = 2 * max(abs(min_y), abs(max_y))

	scale = 1

	if width > 65534 or height > 65534:
		smax = max(width, height)
		scale = 65534.0/smax
		print("Scaling to %.02f%% due to overflow"%(scale*100))

	if len(rframe) >= 65535:
		raise ValueError("Too many points (%d, max 65535)"%len(rframe))



	samples = len(rframe)

	dout = b""
	for i,sample in enumerate(rframe):
		x,y = sample.coord
		x += offx
		y += offy
		x *= scale
		y *= scale
		x = int(x)
		y = int(y)
		mode = 0
		if i == len(rframe):
		    mode |= 0x80
		if params.invert:
			sample.on = not sample.on
		if params.force:
			sample.on = True
		if not sample.on:
		    mode |= 0x40
		if abs(x) > 32767:
			raise ValueError("X out of bounds: %d"%x)
		if abs(y) > 32767:
			raise ValueError("Y out of bounds: %d"%y)

		dout += struct.pack(">hhBB",x,-y,mode, sample.color if sample.on else 0x00)

	return dout,samples

if __name__ == "__main__":
	optimize = True
	verbose = True
	center = True
	params = RenderParameters()

	if sys.argv[1] == "-q":
		verbose = False
		sys.argv = [sys.argv[0]] + sys.argv[2:]

	if sys.argv[1] == "-noopt":
		optimize = False
		sys.argv = [sys.argv[0]] + sys.argv[2:]

	if sys.argv[1] == "-noctr":
		center = False
		sys.argv = [sys.argv[0]] + sys.argv[2:]

	if sys.argv[1] == "-cfg":
		params.load(sys.argv[2])
		sys.argv = [sys.argv[0]] + sys.argv[3:]

	if verbose:
		print("Parse")
	frame = load_svg(sys.argv[1])
	if verbose:
		print("Done")

	if optimize:
		frame.sort()



	if verbose:
		print("Render")
	rframe = frame.render(params)
	if verbose:
		print("Done")

	write_ild(params, rframe, sys.argv[2], center)

	if verbose:
		print("Statistics:")
		print(" Objects: %d"%params.objects)
		print(" Subpaths: %d"%params.subpaths)
		print(" Bezier subdivisions:")
		print("  Due to rate: %d"%params.rate_divs)
		print("  Due to flatness: %d"%params.flatness_divs)
		print(" Points: %d"%params.points)
		print("  Trip: %d"%params.points_trip)
		print("  Line: %d"%params.points_line)
		print("  Bezier: %d"%params.points_bezier)
		print("  Start dwell: %d"%params.points_dwell_start)
		print("  Curve dwell: %d"%params.points_dwell_curve)
		print("  Corner dwell: %d"%params.points_dwell_corner)
		print("  End dwell: %d"%params.points_dwell_end)
		print("  Switch dwell: %d"%params.points_dwell_switch)
		print(" Total on: %d"%params.points_on)
		print(" Total off: %d"%(params.points - params.points_on))
		print(" Efficiency: %.3f"%(params.points_on/float(params.points)))
		print(" Framerate: %.3f"%(params.rate/float(params.points)))