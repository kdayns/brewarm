#!/bin/env python3

import sys
import os
from os import curdir, sep, listdir, path

w1path = '/sys/bus/w1/devices/'

#IOA fe IOB fd on, ff off
IOA = 0x1
IOA_STATUS = 0x02
IOB = 0x2
IOB_STATUS = 0x08

class w1d():

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

    def read(self):
        if self.isTemp():
            try: val = open(w1path + self.id + '/w1_slave').read()
            except:
                print('read sensor %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
                self.curr = self.min
                return False

            pos = val.find('t=')
            if pos == -1: return False

            v = float(val[pos + 2:]) / 1000
            self.curr = min(max(round(v, 3), self.min), self.max)
            return True

        elif self.isSwitch():
            try: val = ord(open(w1path + self.id + '/state', 'rb').read(1))
            except:
                print('read switch %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
                self.curr = 0
                return False

            self.curr = not (val & IOB_STATUS)
            return True

        return False

    def write(self, value):
        if not self.isSwitch(): return False

        try: f = open(w1path + self.id + '/output', 'wb')
        except:
            print('write switch %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
            return False

        b = ~ (IOB if value else 0) & 255
        f.write(bytes([b]))

        return True;
