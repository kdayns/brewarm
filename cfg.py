#!/bin/env python3

import json
import copy
from os import listdir, path, remove

import w1dev

testmode        = path.isfile('.test_mode')
datadir         = 'data'
PORT_NUMBER     = 80
defconfig = {
    'sensors'   : {},
    'active'    : '',
    'running'   : False,
    'update'    : 60,
    'movingavg' : 3,
    'debug'     : 1,
    'sync'      : 60 * 60,
    'i2c_bus'   : 1,
}

debug = False
sensors = []
config = {}
lock = None
# TODO kick csv update
event = None

def acquire():
    #print('acquire')
    lock.acquire()

def release():
    #print('release')
    lock.release()

def getSensorView():
    global sensors
    acquire()
    s = copy.deepcopy(sensors)
    release()
    return s

def unuseSensors():
    global sensors
    acquire()
    for s in sensors: s.used = 0
    release()

def getSensor(id):
    global sensors
    print('get sensor: ' + id)
    acquire()
    for s in sensors:
        if s.id == id:
            release()
            return s
    release()
    return None

def getSensorByName(name):
    global sensors
    print('get sensor: ' + name)
    acquire()
    for s in sensors:
        if s.name == name:
            release()
            return s
    release()
    return None

def getMainSensor():
    s = getSensor(config['main'])
    if s is None: return None
    if s.isTemp() and 'main' in config: return s
    return None

def getMainTemp():
    t = getMainSensor()
    return t.avg if t != None else None

def removeSensor(id):
    print('remove sensor: ' + id)
    acquire()
    for s in cfg.sensors:
        if s.id == id:
            cfg.sensors.remove(s)
            break;
    release()

    store_config()

def updateMainSensor(id):
    global config

    if id is not None:
        print('Main sensor: ' + id)
        config['main'] = id

    m = getMainSensor()
    if m is not None:
        acquire()
        if debug: print('updating range %d - %d' % (m.min, m.max))
        for s in sensors:
            if s.isSwitch():
                s.range(m.min, m.max);
        release()

        store_config()

def isRunning():
    global config
    return config['running']

def store_config():
    global debug, config, sensors

    acquire()
    debug = config['debug']
    configx = copy.deepcopy(config)

    configx['sensors'] = {}
    for s in sensors: configx['sensors'][s.id] = s.dict()
    release()

    if 'brewfiles' in configx: del configx['brewfiles']
    if 'date' in configx: del configx['date']
    if 'tail' in configx: del configx['tail']
    print(json.dumps(configx, indent=True))
    open('config', 'w').write(json.dumps(configx, indent=True))

def read_config():
    global config, sensors
    print("read config")

    config = json.loads(open('config').read())
    if not 'debug' in config: config['debug'] = defconfig['debug']
    if not 'movingavg' in config: config['movingavg'] = defconfig['movingavg']
    if not 'sync' in config: config['sync'] = defconfig['sync']
    if not 'i2c_bus' in config: config['i2c_bus'] = defconfig['i2c_bus']

    # drop unconfigured sensors
    config['sensors'] = { k : v for k,v in config['sensors'].items() if k != v['name'] or v['enabled'] }

    for k,v in config['sensors'].items():
        sensors.append(w1dev.w1d(k, v))

    sensors.sort(key=lambda s: s.id, reverse=True)
    del config['sensors']

def discover_brews():
    global config, sensors
    brews = config['brewfiles']

    for f in listdir('data'):
        if not f.endswith('.csv'): continue
        f = f[:-4]
        if not f in brews: brews.append(f)

def init(l, e):
    global config, debug, lock, event
    print("config init")

    lock = l
    event = e
    config = copy.deepcopy(defconfig)

    if path.isfile('config'):
        read_config()

    if path.isfile('.clean_shutdown'):
        config['running'] = False
        store_config()
        remove('.clean_shutdown')

    config['brewfiles'] = []
    discover_brews()

    debug = config['debug']

    print(json.dumps(config, indent=True))
