from __future__ import absolute_import

import sys
import math
import re
import os

from Cura.util import util3d
from Cura.util import profile

class gcodePath(object):
	def __init__(self, newType, pathType, layerThickness, startPoint):
		self.type = newType
		self.pathType = pathType
		self.layerThickness = layerThickness
		self.list = [startPoint]

class gcode(object):
	def __init__(self):
		self.regMatch = {}
		self.layerList = []
		self.extrusionAmount = 0
		self.totalMoveTimeMinute = 0
		self.progressCallback = None
	
	def load(self, filename):
		if os.path.isfile(filename):
			self._fileSize = os.stat(filename).st_size
			gcodeFile = open(filename, 'r')
			self._load(gcodeFile)
			gcodeFile.close()
	
	def loadList(self, l):
		self._load(l)
	
	def calculateWeight(self):
		#Calculates the weight of the filament in kg
		radius = float(profile.getProfileSetting('filament_diameter')) / 2
		volumeM3 = (self.extrusionAmount * (math.pi * radius * radius)) / (1000*1000*1000)
		return volumeM3 * profile.getPreferenceFloat('filament_density')
	
	def calculateCost(self):
		cost_kg = profile.getPreferenceFloat('filament_cost_kg')
		cost_meter = profile.getPreferenceFloat('filament_cost_meter')
		if cost_kg > 0.0 and cost_meter > 0.0:
			return "%.2f / %.2f" % (self.calculateWeight() * cost_kg, self.extrusionAmount / 1000 * cost_meter)
		elif cost_kg > 0.0:
			return "%.2f" % (self.calculateWeight() * cost_kg)
		elif cost_meter > 0.0:
			return "%.2f" % (self.extrusionAmount / 1000 * cost_meter)
		return None
	
	def _load(self, gcodeFile):
		filePos = 0
		pos = util3d.Vector3()
		posOffset = util3d.Vector3()
		currentE = 0.0
		totalExtrusion = 0.0
		maxExtrusion = 0.0
		currentExtruder = 0
		extrudeAmountMultiply = 1.0
		totalMoveTimeMinute = 0.0
		absoluteE = True
		scale = 1.0
		posAbs = True
		feedRate = 3600
		layerThickness = 0.1
		pathType = 'CUSTOM';
		startCodeDone = False
		currentLayer = []
		currentPath = gcodePath('move', pathType, layerThickness, pos.copy())
		currentPath.list[0].e = totalExtrusion
		currentPath.list[0].extrudeAmountMultiply = extrudeAmountMultiply
		currentLayer.append(currentPath)
		for line in gcodeFile:
			if type(line) is tuple:
				line = line[0]

			#Parse Cura_SF comments
			if line.startswith(';TYPE:'):
				pathType = line[6:].strip()
				if pathType != "CUSTOM":
					startCodeDone = True
					
			if ';' in line:
				#Slic3r GCode comment parser
				comment = line[line.find(';')+1:].strip()
				if comment == 'fill':
					pathType = 'FILL'
				elif comment == 'perimeter':
					pathType = 'WALL-INNER'
				elif comment == 'skirt':
					pathType = 'SKIRT'
				if comment.startswith('LAYER:'):
					self.layerList.append(currentLayer)
					if self.progressCallback is not None:
						if filePos != gcodeFile.tell():
							filePos = gcodeFile.tell()
							if self.progressCallback(float(filePos) / float(self._fileSize)):
								#Abort the loading, we can safely return as the results here will be discarded
								gcodeFile.close()
								return
					currentLayer = []
				if pathType != "CUSTOM":
					startCodeDone = True
				line = line[0:line.find(';')]
			T = self.getCodeInt(line, 'T')
			if T is not None:
				if currentExtruder > 0:
					posOffset.x -= profile.getPreferenceFloat('extruder_offset_x%d' % (currentExtruder))
					posOffset.y -= profile.getPreferenceFloat('extruder_offset_y%d' % (currentExtruder))
				currentExtruder = T
				if currentExtruder > 0:
					posOffset.x += profile.getPreferenceFloat('extruder_offset_x%d' % (currentExtruder))
					posOffset.y += profile.getPreferenceFloat('extruder_offset_y%d' % (currentExtruder))
			
			G = self.getCodeInt(line, 'G')
			if G is not None:
				if G == 0 or G == 1:	#Move
					x = self.getCodeFloat(line, 'X')
					y = self.getCodeFloat(line, 'Y')
					z = self.getCodeFloat(line, 'Z')
					e = self.getCodeFloat(line, 'E')
					f = self.getCodeFloat(line, 'F')
					oldPos = pos.copy()
					if x is not None:
						if posAbs:
							pos.x = x * scale + posOffset.x
						else:
							pos.x += x * scale
					if y is not None:
						if posAbs:
							pos.y = y * scale + posOffset.y
						else:
							pos.y += y * scale
					if z is not None:
						if posAbs:
							pos.z = z * scale + posOffset.z
						else:
							pos.z += z * scale
					if f is not None:
						feedRate = f
					if x is not None or y is not None or z is not None:
						totalMoveTimeMinute += (oldPos - pos).vsize() / feedRate
					moveType = 'move'
					if e is not None:
						if not absoluteE:
							e += currentE
						if posAbs:
							if e > currentE:
								moveType = 'extrude'
							if e < currentE:
								moveType = 'retract'
						else:
							if e > 0:
								moveType = 'extrude'
							if e < 0:
								moveType = 'retract'
						totalExtrusion += e - currentE
						currentE = e
						if totalExtrusion > maxExtrusion:
							maxExtrusion = totalExtrusion
					if moveType == 'move' and oldPos.z != pos.z:
						if oldPos.z > pos.z and abs(oldPos.z - pos.z) > 5.0 and pos.z < 1.0:
							oldPos.z = 0.0
						layerThickness = abs(oldPos.z - pos.z)
					if currentPath.type != moveType or currentPath.pathType != pathType:
						currentPath = gcodePath(moveType, pathType, layerThickness, currentPath.list[-1])
						currentLayer.append(currentPath)
					newPos = pos.copy()
					newPos.e = totalExtrusion
					newPos.extrudeAmountMultiply = extrudeAmountMultiply
					currentPath.list.append(newPos)
				elif G == 4:	#Delay
					S = self.getCodeFloat(line, 'S')
					if S is not None:
						totalMoveTimeMinute += S / 60
					P = self.getCodeFloat(line, 'P')
					if P is not None:
						totalMoveTimeMinute += P / 60 / 1000
				elif G == 20:	#Units are inches
					scale = 25.4
				elif G == 21:	#Units are mm
					scale = 1.0
				elif G == 28:	#Home
					x = self.getCodeFloat(line, 'X')
					y = self.getCodeFloat(line, 'Y')
					z = self.getCodeFloat(line, 'Z')
					if x is None and y is None and z is None:
						pos = util3d.Vector3()
					else:
						if x is not None:
							pos.x = 0.0
						if y is not None:
							pos.y = 0.0
						if z is not None:
							pos.z = 0.0
				elif G == 90:	#Absolute position
					posAbs = True
				elif G == 91:	#Relative position
					posAbs = False
				elif G == 92:
					x = self.getCodeFloat(line, 'X')
					y = self.getCodeFloat(line, 'Y')
					z = self.getCodeFloat(line, 'Z')
					e = self.getCodeFloat(line, 'E')
					if e is not None:
						currentE = e
					if x is not None:
						posOffset.x = pos.x - x
					if y is not None:
						posOffset.y = pos.y - y
					if z is not None:
						posOffset.z = pos.z - z
				else:
					print "Unknown G code:" + str(G)
			else:
				M = self.getCodeInt(line, 'M')
				if M is not None:
					if M == 1:	#Message with possible wait (ignored)
						pass
					elif M == 80:	#Enable power supply
						pass
					elif M == 81:	#Suicide/disable power supply
						pass
					elif M == 82:   #Absolute E
						absoluteE = True
					elif M == 83:   #Relative E
						absoluteE = False
					elif M == 84:	#Disable step drivers
						pass
					elif M == 92:	#Set steps per unit
						pass
					elif M == 101:	#Enable extruder
						pass
					elif M == 103:	#Disable extruder
						pass
					elif M == 104:	#Set temperature, no wait
						pass
					elif M == 105:	#Get temperature
						pass
					elif M == 106:	#Enable fan
						pass
					elif M == 107:	#Disable fan
						pass
					elif M == 108:	#Extruder RPM (these should not be in the final GCode, but they are)
						pass
					elif M == 109:	#Set temperature, wait
						pass
					elif M == 110:	#Reset N counter
						pass
					elif M == 113:	#Extruder PWM (these should not be in the final GCode, but they are)
						pass
					elif M == 140:	#Set bed temperature
						pass
					elif M == 190:	#Set bed temperature & wait
						pass
					elif M == 221:	#Extrude amount multiplier
						s = self.getCodeFloat(line, 'S')
						if s != None:
							extrudeAmountMultiply = s / 100.0
					else:
						print "Unknown M code:" + str(M)
		self.layerList.append(currentLayer)
		self.extrusionAmount = maxExtrusion
		self.totalMoveTimeMinute = totalMoveTimeMinute
		#print "Extruded a total of: %d mm of filament" % (self.extrusionAmount)
		#print "Estimated print duration: %.2f minutes" % (self.totalMoveTimeMinute)

	def getCodeInt(self, line, code):
		if code not in self.regMatch:
			self.regMatch[code] = re.compile(code + '([^\s]+)')
		m = self.regMatch[code].search(line)
		if m == None:
			return None
		try:
			return int(m.group(1))
		except:
			return None

	def getCodeFloat(self, line, code):
		if code not in self.regMatch:
			self.regMatch[code] = re.compile(code + '([^\s]+)')
		m = self.regMatch[code].search(line)
		if m == None:
			return None
		try:
			return float(m.group(1))
		except:
			return None

if __name__ == '__main__':
	for filename in sys.argv[1:]:
		gcode().load(filename)

