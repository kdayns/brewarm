#!/bin/env python3

import sys
from os import curdir, sep, listdir, path

w1path = '/sys/bus/w1/devices/'

class w1d:
    def __init__(self, _id, _dictstr = None):
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
                self.dev = 'ds2413'
            else:
                self.dev = ''
                print('unknown device: ' + self.id)
        else:
            if not 'dev' in _dictstr: _dictstr['dev'] = 'ds18b20'
            self.dev = _dictstr['dev']
            self.name = _dictstr['name']
            self.enabled = _dictstr['enabled']

            if self.dev == 'ds18b20':
                self.curr = _dictstr['curr']
                self.avg = _dictstr['avg']
                self.min = _dictstr['min']
                self.max = _dictstr['max']

    def isTemp(self):
        return self.dev == 'ds18b20'

    def dict(self):
        return { key:value for key, value in self.__dict__.items()
                if not key.startswith('__') and not callable(value) }

    def read(self):
        if self.dev == 'ds18b20':
            try: val = open(w1path + self.id + '/w1_slave').read()
            except:
                print('read sensor %s failed: %s ' % (self.id, str(sys.exc_info()[0])))
                self.curr = self.min
                return None

            pos = val.find('t=')
            v = float(val[pos + 2:]) / 1000
            self.curr = min(max(round(v, 3), self.min), self.max)
            return v

        elif self.dev == 'ds2413':
            # TODO
            return None

        return None
