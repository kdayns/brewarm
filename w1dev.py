#!/bin/env python3

from pids import Pid
import sys
import os
import time
from os import curdir, sep, listdir, path

w1path = '/sys/bus/w1/devices/'
pidTemp = None
sw_ds18b20 = False
sw_ds2413 = False

#IOA fe IOB fd on, ff off
IOA = 0x1
IOA_STATUS = 0x02
IOB = 0x2
IOB_STATUS = 0x08

MODE_COOL = 0
MODE_HEAT = 1

class w1d(Pid):

    def isTemp(self): return self.dev == 'ds18b20'
    def isSwitch(self): return self.dev == 'ds2413'

    def __init__(self, _id, _dictstr = None):
        self._mtime = 0
        self.id = _id
        self.name = _id
        self.used = False    # if used in active brew

        if _dictstr == None:
            self.enabled = True  # collect temperature, add to new brew
            if path.isfile(w1path + self.id + '/w1_slave'):
                self.curr = 0
                self.avg = 0
                self.min = -20
                self.max = 100
                self.dev = 'ds18b20'
            elif path.isfile(w1path + self.id + '/output'):
                self.curr = 0
                self.dev = 'ds2413'
                self.set(0)
                self.mode = MODE_COOL
                self.tune(5, 0.25, -1.5)
                self.range(-100, 100)
            else:
                self.dev = ''
                print('unknown device: ' + self.id)
        else:
            if not 'dev' in _dictstr: _dictstr['dev'] = 'ds18b20'
            self.dev = _dictstr['dev']
            self.name = _dictstr['name']
            self.enabled = _dictstr['enabled']

            if self.isTemp():
                self.curr = _dictstr['curr']
                self.avg = _dictstr['avg']
                self.min = _dictstr['min']
                self.max = _dictstr['max']
            elif self.isSwitch():
                self.set(_dictstr['setpoint'])
                self.tune(_dictstr['Kp'], _dictstr['Ki'], _dictstr['Kd'])
                self.range(-100, 100)

    def dict(self):
        return { key:value for key, value in self.__dict__.items()
                if not key.startswith('_') and not callable(value) }

    def changed(self):
        f = w1path + self.id
        if self.isTemp(): f += '/w1_slave'
        elif self.isSwitch(): f += '/state'
        else: return False

        try:
            nt = os.stat(f).st_mtime
            if nt == self._mtime: return False
        except: return False

        self._mtime = nt;
        return True

    def sw_write (self, cmd):
        with open(w1path + self.id + '/rw', 'wb', 0) as f:
            f.write(cmd)

    def sw_read (self, s):
        with open(w1path + self.id + '/rw', 'rb', 0) as f:
            t = f.read(s)
        return t

    def read(self):
        if self.isTemp(): return self.readTemp()
        elif self.isSwitch(): return self.readSwitch()
        return False

    def readTemp(self):
        v = 0
        try:
            if sw_ds18b20:
                self.sw_write(b'\x44') # start conv
                # max Tconv 750ms
                while True:
                    time.sleep(0.1)
                    r = self.sw_read(1)[0]
                    if r: break
                self.sw_write(b'\xbe') # read result
                time.sleep(0.1)

                ret = self.sw_read(2)
                buf0 = ret[0]
                buf1 = ret[1]
                t = buf1 << 8 | buf0

                if buf0 == 0xff:
                    print('read sw sensor %s failed: %d %x ' % (self.id, len(ret), t))
                    self.curr = None
                    return False

                if t & 0x8000: # sign bit set
                    t = -((t ^ 0xffff) + 1)
                v = t / 16
            else:
                val = open(w1path + self.id + '/w1_slave').read()
                pos = val.find('t=')
                if pos == -1:
                    print('read sensor %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
                    self.curr = None
                    return False

                v = float(val[pos + 2:]) / 1000

        except:
            print('read sensor %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
            self.curr = None
            return False

        self.curr = min(max(round(v, 3), self.min), self.max)
        return True

    def readSwitch(self):
        val = 0
        try:
            if not sw_ds2413:
                val = ord(open(w1path + self.id + '/state', 'rb').read(1))
            else:
                self.sw_write(b'\xf5')
                ret = self.sw_read(1)

                buf0 = ret[0]
                if (buf0 & 0x0F) != ((~buf0 >> 4) & 0x0F):
                    print ("read switch sw failed")
                    self.curr = 0
                    return False
                else: val = buf0
        except:
            print('read switch %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
            self.curr = 0
            return False

        self.curr = not (val & IOB_STATUS)
        print ('Switch %s state %x (raw %x)' % (self.id, self.curr, val))
        return True

    def write(self, value):
        if not self.isSwitch(): return False

        print ('Switch %s write state %x' % (self.id, value))
        value = ~ (IOB if value else 0) & 255

        try:
            if not sw_ds2413:
                open(w1path + self.id + '/output', 'wb').write(bytes([value]))
            else:
                value = value | 0xFC
                self.sw_write(bytearray([ 0x5A, value, ~value & 0xff ]))
                r = self.sw_read(2)
                if r[0] != 0xAA:
                    print('write switch %s failed: %x' % (self.id, r[0]))
                    return False
                print ('Switch %s state after write %x' % (self.id, not (r[1] & IOB_STATUS)))
        except:
            print('write switch %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
            return False

        return True;

    def pid(self):
        if not self.isSwitch(): return False

        self.step(1.0, pidTemp())
        self.write(self.get() > 0)

        print('PID out=' + str(self.get()) + "  t=" + str(pidTemp()))

        return True
