#!/usr/bin/env python3

import random
import time
import sys

w1path = './sys/bus/w1/devices/'
t1 = w1path + 'temp1/w1_slave'
s1 = w1path + 'sw1/'

print ("sim")

while True:
    t = random.random() % 10 * 10 + 20
    print ("new temp: " + str(t))
    try: f = open(t1, 'w').write('t=%d' % round(t * 1000))
    except: print('write sensor %s failed: %s ' % (t1, str(sys.exc_info()[0])))
    time.sleep(1);
