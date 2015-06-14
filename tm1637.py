#!/bin/env python3

# copy from sd582's implementation on some German forum

import sys
import os
import time
import RPi.GPIO as IO

HexDigits = [0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,0x77,0x7c,0x39,0x5e,0x79,0x71]

ADDR_AUTO = 0x40
ADDR_FIXED = 0x44
STARTADDR = 0xC0
BRIGHT_DARKEST = 0
BRIGHT_TYPICAL = 2
BRIGHT_HIGHEST = 6
OUTPUT = IO.OUT
INPUT = IO.IN
LOW = IO.LOW
HIGH = IO.HIGH

class TM1637:
	__doublePoint = False
	__Clkpin = 0
	__Datapin = 0
	__brightnes = BRIGHT_TYPICAL;
	__currentData = [0,0,0,0];
	
	def __init__( self, pinClock, pinData, brightnes ):
		IO.setwarnings(False)
		IO.setmode(IO.BOARD)

		self.__Clkpin = pinClock
		self.__Datapin = pinData
		self.__brightnes = brightnes;
		IO.setup(self.__Clkpin,OUTPUT)
		IO.setup(self.__Datapin,OUTPUT)

	def Clear(self):
		b = self.__brightnes;
		point = self.__doublePoint;
		self.__brightnes = 0;
		self.__doublePoint = False;
		data = [0x7F,0x7F,0x7F,0x7F];
		self.Show(data);
		self.__brightnes = b;				# restore saved brightnes
		self.__doublePoint = point;

	def Show( self, data ):
		if (not self.connected()): return

		for i in range(0,4):
			self.__currentData[i] = data[i];
		
		self.start();
		self.writeByte(ADDR_AUTO);
		self.stop();
		self.start();
		self.writeByte(STARTADDR);
		for i in range(0,4):
			self.writeByte(self.coding(data[i], i));
		self.stop();
		self.start();
		self.writeByte(0x88 + self.__brightnes);
		self.stop();

	def Show1(self, DigitNumber, data):	# show one Digit (number 0...3)
		if (not self.connected()): return

		if( DigitNumber < 0 or DigitNumber > 3):
			return;	# error
	
		self.__currentData[DigitNumber] = data;
		
		self.start();
		self.writeByte(ADDR_FIXED);
		self.stop();
		self.start();
		self.writeByte(STARTADDR | DigitNumber);
		self.writeByte(self.coding(data, DigitNumber));
		self.stop();
		self.start();
		self.writeByte(0x88 + self.__brightnes);
		self.stop();
		
	def SetBrightnes(self, brightnes):		# brightnes 0...7
		if( brightnes > 7 ):
			brightnes = 7;
		elif( brightnes < 0 ):
			brightnes = 0;

		if( self.__brightnes != brightnes):
			self.__brightnes = brightnes;
			self.Show(self.__currentData);

	def ShowDoublepoint(self, on):			# shows or hides the doublepoint
		if( self.__doublePoint != on):
			self.__doublePoint = on;
			self.Show(self.__currentData);
			
	def writeByte( self, data ):
		for i in range(0,8):
			IO.output( self.__Clkpin, LOW)
			if(data & 0x01):
				IO.output( self.__Datapin, HIGH)
			else:
				IO.output( self.__Datapin, LOW)
			data = data >> 1
			IO.output( self.__Clkpin, HIGH)
		#endfor

		# wait for ACK
		IO.output( self.__Clkpin, LOW)
		IO.output( self.__Datapin, HIGH)
		IO.output( self.__Clkpin, HIGH)
		IO.setup(self.__Datapin, INPUT)
		
		while(IO.input(self.__Datapin)):
			time.sleep(0.001)
			if( IO.input(self.__Datapin)):
				IO.setup(self.__Datapin, OUTPUT)
				IO.output( self.__Datapin, LOW)
				IO.setup(self.__Datapin, INPUT)
			#endif
		# endwhile            
		IO.setup(self.__Datapin, OUTPUT)
    
	def start(self):
		IO.output( self.__Clkpin, HIGH) # send start signal to TM1637
		IO.output( self.__Datapin, HIGH)
		IO.output( self.__Datapin, LOW) 
		IO.output( self.__Clkpin, LOW) 
	
	def stop(self):
		IO.output( self.__Clkpin, LOW) 
		IO.output( self.__Datapin, LOW) 
		IO.output( self.__Clkpin, HIGH)
		IO.output( self.__Datapin, HIGH)
	
	def coding(self, data, idx):
		if( self.__doublePoint and idx == 1 ):
			pointData = 0x80
		else:
			pointData = 0;
		
		if(data == 0x7F):
			data = 0
		else:
			data = HexDigits[data] + pointData;
		return data

	def connected(self):
		IO.setup(self.__Clkpin,INPUT)
		val = IO.input(self.__Clkpin)
		IO.setup(self.__Clkpin,OUTPUT)
		return val

## =============================================================
# -----------  Test -------------

if __name__ == "__main__":
    Display = TM1637(16,15, BRIGHT_HIGHEST)
    if (not Display.connected()):
        print('display not connected')
        sys.exit(1)

    Display.Clear()
    Display.ShowDoublepoint(True)

    for i in range(0,9999):
        t = i // 1000 % 10
        s = (i - t) // 100 % 10
        d = (i - t - s) // 10 % 10
        v = (i - t - s - d) % 10
        disp = [t,s,d,v]
        Display.Show(disp)
        #time.sleep(1)

    Display.Clear()
