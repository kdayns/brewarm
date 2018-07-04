#!/usr/bin/env python3

import gzip
import sys
import signal
import copy
import io
import os
import json
import time
import shutil;
import http.server
import socketserver
from os import curdir, sep, listdir, path
import datetime;
import subprocess;
import threading;
import email.utils as eut
import w1dev
from w1dev import w1d

testmode        = path.isfile('.test_mode')
shutdown_pin    = None # gpio pin number 7
datadir         = 'data'
PORT_NUMBER     = 80
defconfig = {
    'sensors'   : {},
    'active'    : '',
    'running'   : False,
    'update'    : 60,
    'decimate'  : 4,
    'debug'     : 1,
    'sync'      : 60 * 60,
    'i2c_bus'   : 1,
}
config = copy.deepcopy(defconfig)

# private
lcd = None
csv = None
comment = None
latest = []
sensors = []
lock = threading.Lock()
event = threading.Event()
lastSync = datetime.datetime.now()

if not testmode:
    subprocess.call(['modprobe', 'w1-gpio', 'gpiopin=10'])
    if subprocess.call(['modprobe', 'w1_therm']):
        w1dev.sw_ds18b20 = True
        print('using sw ds18b20')
    if subprocess.call(['modprobe', 'w1_ds2413']):
        w1dev.sw_ds2413 = True
        print('using sw ds2413')
    os.chdir('/opt/brewarm')
else:
    w1dev.w1path = '.' + w1dev.w1path

def getMain():
    global config, sensors
    for s in sensors:
        if s.isTemp() and 'main' in config and s.id == config['main']:
            return s
    return None

def getMainTemp():
    t = getMain()
    return t.avg if t != None else None

w1dev.pidTemp = lambda : getMainTemp()

def store_config():
    global debug, config, sensors

    debug = config['debug']
    configx = copy.deepcopy(config)

    configx['sensors'] = {}
    lock.acquire()
    for s in sensors: configx['sensors'][s.id] = s.dict()
    lock.release()

    if 'brewfiles' in configx: del configx['brewfiles']
    if 'date' in configx: del configx['date']
    if 'tail' in configx: del configx['tail']
    print(json.dumps(configx, indent=True))
    open('config', 'w').write(json.dumps(configx, indent=True))

if path.isfile('config'):
    config = json.loads(open('config').read())
    if not 'debug' in config: config['debug'] = defconfig['debug']
    if not 'decimate' in config: config['decimate'] = defconfig['decimate']
    if not 'sync' in config: config['sync'] = defconfig['sync']
    if not 'i2c_bus' in config: config['i2c_bus'] = defconfig['i2c_bus']

    # migrate
    if len(config['sensors']) and type(next(iter(config['sensors'].values()))) is not dict:
         print('migrate list -> dict')
         s = {}
         for k,v in config['sensors'].items():
             s[k] = { 'name':v[0], 'curr':v[1], 'avg':v[2], 'enabled':v[3], 'min':-20, 'max':100 }
         config['sensors'] = s
    # drop unconfigured sensors
    config['sensors'] = { k : v for k,v in config['sensors'].items() if k != v['name'] or v['enabled'] }

    for k,v in config['sensors'].items():
        sensors.append(w1d(k, v))

    sensors.sort(key=lambda s: s.id, reverse=True)
    del config['sensors']

if path.isfile('.clean_shutdown'):
    config['running'] = False
    store_config()
    os.remove('.clean_shutdown')

config['brewfiles'] = []
debug = config['debug']

if 0: # rpi lcd
    import tm1637
    lcd = tm1637.TM1637(16,15, tm1637.BRIGHT_HIGHEST)
    lcd.ShowDoublepoint(True)
    lcd.Clear()

if 0: # hw clock
    open('/sys/class/i2c-adapter/i2c-' + str(config['i2c_bus']) + '/new_device', 'w').write("ds1307 0x68")
    subprocess.call(['hwclock', '-s']) # load clock from rtc

def thread_update_temp(s):
    global lcd
    decimate = config['decimate']

    s.avg = 0
    cnt = 0
    retried = False
    for i in range(decimate):
        if not s.read():
            if retried: break
            retried = True
            continue
        s.avg += s.curr
        cnt += 1
    if not cnt: s.avg = None
    else:
        s.avg = round(s.avg / cnt, 3)
        if s.curr is None: s.avg
    if debug: print("data: %s %s %d" % (s.id, s.avg, cnt))

    if lcd is not None and config['main'] == s.id:
        # TODO - negative numbers
        if s.avg is None: lcd.Clear()
        else:
            la = [int(i) for i in list(str(round(s.avg, 2)).replace('.', ''))]
            for i in range(4 - len(la)): la.append(0)
            lcd.Show(la)
    return

def sync(toTemp = False):
    print('syncing.. ' + str(toTemp))
    f = datadir + '/' + config['active'] + '.csv'
    t = '/tmp/' + config['active']
    if toTemp:
        if path.isfile(f): shutil.copyfile(f, t)
    else:
        if path.isfile(t):
            shutil.copyfile(t, f + '_tmp')
            shutil.move(f + '_tmp', f)
        else:
            print("temp not present")

def read_all(now, lastRead):
        global sensors
        rthreads = []
        lock.acquire()

        t = not w1dev.sw_ds18b20
        # threaded reading works faster
        for s in sensors:
            if s.isTemp():
                if not s.enabled:
                    s.avg = None
                    s.curr = None
                    continue
                if not t: thread_update_temp(s)
                else:
                    th = threading.Thread(daemon=True, target=thread_update_temp, args=(s,))
                    th.start()
                    rthreads.append(th)
        if t:
            for th in rthreads: th.join()

        for s in sensors:
            if s.isSwitch():
                # TODO - force
                if lastRead is not None: s.pid((now - lastRead).total_seconds())
                else: s.pid(0)
                s.read()
                print("state: " + str(s.curr))

        lock.release()

def thread_temp():
    global config, sensors, csv, event, latest, lastSync, comment
    lastActive = ''
    lastRead = None

    while True:
        now = datetime.datetime.now()
        read_all(now, lastRead)
        lastRead = now
        print('-- reading sensors took: ' + str(datetime.datetime.now() - now))

        # write file
        if config['running'] == False:
            latest = []
            lastActive = ''
            if csv != None:
                csv.close()
                csv = None
                lock.acquire()
                for s in sensors: s.used = 0
                lock.release()
                sync()
        else:
            if lastActive != config['active']:
                latest = []
                if csv != None:
                    csv.close()
                    sync()
                try:
                    if config['sync']:
                        sync(True)
                        csv = open('/tmp/' + config['active'], 'a+')
                    else: csv = open(datadir + '/' + config['active'] + '.csv', 'a+')
                    size = csv.tell()

                    print('appending: ' + config['active'])
                    # get used sensors
                    csv.seek(0, io.SEEK_SET)
                    l = csv.readline().strip()
                    if l[:6] != '#date,': raise
                    l = l[6:]

                    lock.acquire()
                    for s in sensors: s.used = 0
                    idx = 1
                    for item in l.split(','):
                        for s in sensors:
                            if s.name == item:
                                s.used = idx
                                idx += 1
                                break
                    lock.release()

                    # date recovery
                    csv.seek(size - min(128, size), io.SEEK_SET)
                    tail = csv.read(128)
                    if len(tail) > 5 and tail.rfind('\n', 0, -2) != -1:
                        tail = tail[tail.rfind('\n', 0, -2) + 1:].strip()
                        if debug: print('tail: ' + tail)
                        tail = tail[:tail.find(',')]
                        last = datetime.datetime.strptime(tail, '%Y/%m/%d %H:%M:%S')
                        if debug: print('last: ' + str(last))
                        if last > now:
                            print('time adjust')
                            subprocess.call(['date', '-s', tail])
                    csv.seek(0, io.SEEK_END)
                    lastActive = config['active']
                except:
                    raise
                    print('csv open failed: ' + str(sys.exc_info()[0]))
                    if csv != None:
                        csv.close()
                        csv = None

            # csv writer
            if csv != None:
                newdata = []
                newdata.append(int(now.timestamp() * 1000))
                csv.write(now.strftime('%Y/%m/%d %H:%M:%S'))

                lock.acquire()
                ssens = copy.deepcopy(sensors)
                ssens.sort(key=lambda s: s.used)
                for s in ssens:
                    if not s.used: continue
                    csv.write(',')

                    if not s.enabled:
                        v = None
                    elif s.isSwitch():
                        if s.curr:
                            v = 1
                            csv.write('true')
                        else:
                            v = 0
                            csv.write('false')
                    elif s.isTemp():
                        v = s.avg
                        if s.avg is not None: csv.write(str(v))
                    # TODO - none
                    #if v is None:
                    newdata.append(v)

                if comment != None:
                    for s in sensors:
                        if s.name != comment['sensor']: continue
                        csv.write(' #' + str(s.used - 1) + ' ' + comment['string'])
                        break
                    comment = None
                lock.release()

                csv.write('\n')
                csv.flush()
                latest.append(newdata)
                if len(latest) > 10: latest.pop(0)
                if config['sync'] and (now - lastSync).total_seconds() > config['sync']:
                    lastSync = now
                    sync()

        if debug: print('waiting: ', config['update'])

        if testmode:
            ch = False
            while not ch:
                lock.acquire()
                for s in sensors:
                    ch |= s.changed()
                lock.release()
                if not ch: threading.Event().wait(timeout=1)
            print("changed")
        else:
            event.wait(timeout=config['update'])
            event.clear()

def thread_shutdown():
    global config

    try: open('/sys/class/gpio/export', 'w').write(str(shutdown_pin))
    except: print('export failed: ' + str(sys.exc_info()[0]))

    while True:
        val = ''
        try: val = open('/sys/class/gpio/gpio%u/value' % shutdown_pin).read().strip()
        except: print('gpio open failed: ' + str(sys.exc_info()[0]))
        if val == '1':
            print('shutdown')
            if config['sync']: sync()
            open('.clean_shutdown', 'w').close()
            subprocess.call(['shutdown', '-h', 'now'])
            return;
        threading.Event().wait(timeout=5)
    return

def thread_discovery():
    global config, sensors
    brews = config['brewfiles']

    while True:
        # monitor data dir
        for f in listdir('data'):
            if not f.endswith('.csv'): continue
            f = f[:-4]
            if not f in brews: brews.append(f)

        # monitor w1
        found = False
        for f in listdir(w1dev.w1path):
            if f == 'w1_bus_master1': continue
            if not path.isdir(w1dev.w1path + '/' + f): continue

            lock.acquire()
            exists = False
            for s in sensors:
                if s.id == f:
                    exists = True
                    break

            if not exists:
                print("new sensor: " + f)
                found = True
                sensors.append(w1d(f))
            lock.release()

        if found:
            store_config()
            event.set()

        threading.Event().wait(timeout=5)
    return

class BrewHTTPHandler(http.server.BaseHTTPRequestHandler):
    def sendStatus(self):
        global config, latest, sensors
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

        status = copy.deepcopy(config)
        status['sensors'] = []
        lock.acquire()
        for s in sensors:
            status['sensors'].append(s.dict())
        lock.release()
        status['tail'] = latest
        status['date'] = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
        self.wfile.write(bytearray(json.dumps(status), 'utf-8'))

    def log_message(self, format, *args):
        if not debug: return
        http.server.BaseHTTPRequestHandler.log_message(self, format, *args)

    def handle_one_request(self):
        try:
            http.server.BaseHTTPRequestHandler.handle_one_request(self)
        except:
            if debug: raise
            else: print('Unknown error: %s' % sys.exc_info()[0])

    def do_GET(self):
        if self.path=="/": self.path="/index.html"

        if self.path=="/data/": self.handleData()
        else: self.handleFile()

    def do_POST(self):
        global config, event
        varLen = int(self.headers['Content-Length'])
        postVars = str(self.rfile.read(varLen), 'utf-8')

        if not len(postVars):
            self.sendStatus()
            return;

        if debug:
            print('post: ' + postVars)

        if self.path == '/comment': self.handleComment(postVars)
        elif self.path == '/main': self.handleMain(postVars)
        elif self.path == '/remove': self.handleRemove(postVars)
        elif self.path == '/toggle': self.handleToggle(postVars)
        else: self.handleConfig(postVars)

    def handleComment(self, postVars):
        global comment, config, sensors
        if comment != None:
            self.send_error(500,'Comment pending!')
            return

        if config['running'] == False:
            self.send_error(500,'Not running')
            return

        post = json.loads(postVars)
        lock.acquire()
        active = False
        for s in sensors:
            if s.name == post['sensor']:
                active = s.enabled
                break
        lock.release()

        if active == False:
            self.send_error(500,'Sensor not used in current brew!')
            return

        comment = {}
        comment['sensor'] = post['sensor']
        comment['string'] = post['comment']
        event.set()

        self.send_response(200)
        self.end_headers()
        return

    def handleMain(self, postVars):
        global lcd, config, sensors

        post = json.loads(postVars)
        config['main'] = post['sensor']
        print('Main sensor: ' + config['main'])

        m = getMain()
        if m is not None:
            if debug: print('updating range %d - %d' % (m.min, m.max))
            lock.acquire()
            for s in sensors:
                if s.isSwitch():
                    s.range(m.min, m.max);
            lock.release()

        store_config()
        event.set()

        if lcd == None:
            self.send_error(500, 'Not present!')
            return

        if not lcd.connected():
            self.send_error(500,'Not connected!')
            return

        self.send_response(200)
        self.end_headers()
        return

    def handleRemove(self, postVars):
        global sensors
        post = json.loads(postVars)
        print('remove sensor: ' + post['sensor'])

        lock.acquire()
        for s in sensors:
            if s.id == post['sensor']:
                sensors.remove(s)
                break;
        lock.release()

        store_config()

        self.send_response(200)
        self.end_headers()
        return

    def handleToggle(self, postVars):
        global sensors
        post = json.loads(postVars)
        print('toggle sensor: ' + post['sensor'])

        lock.acquire()
        for s in sensors:
            if s.id == post['sensor']:
                s.write(post['value'])
                s.read()
                break;
        lock.release()

        self.send_response(200)
        self.end_headers()
        return

    def handleConfig(self, postVars):
        global sensors, config, debug

        nc = json.loads(postVars)
        if 'command' in nc:
            cmd = nc['command']
            print('command: ' + cmd)
            if cmd == 'shutdown' or cmd == 'reboot':
                open('.clean_shutdown', 'w').close()
                if cmd == 'shutdown': subprocess.call(['shutdown', '-h', 'now'])
                else: subprocess.call(['reboot'])
            elif cmd == 'kill':
                os.remove('data/' + nc['name'] + '.csv')
                for b in config['brewfiles']:
                    if b == nc['name']: config['brewfiles'].remove(b)
            self.send_response(200)
            self.end_headers()
            return

        if debug: print('current config: ' + json.dumps(config))

        if 'sensors' in nc:
            lock.acquire()
            for k,v in nc['sensors'].items():
                for s in sensors:
                    if not s.id == k: continue

                    if debug: print('updating ' + s.name + ' ' + json.dumps(v))
                    if s.name != v[0]: s.name = v[0]
                    if s.enabled != v[1]: s.enabled = v[1]

                    if s.isTemp():
                        if s.min != v[2]: s.min = int(v[2])
                        if s.max != v[3]: s.max = int(v[3])
                    elif s.isSwitch():
                        # override state if s.state != v[2]: s.state = int(v[2])
                        s.setpoint = int(v[3])
                        s.mode = int(v[4])
                    break;

            m = getMain()
            if m is not None:
                if debug: print('updating range %d - %d' % (m.min, m.max))
                for s in sensors:
                    if s.isSwitch():
                        s.range(m.min, m.max);
            lock.release()

        #if 'main' in nc: config['main'] = nc['main']
        if 'active' in nc and config['active'] != nc['active']:
                print('new data file: ' + nc['active'])

                if config['sync']:
                    sync(True)
                    csv = open('/tmp/' + nc['active'], 'a+')
                else: csv = open(datadir + '/' + nc['active'] + '.csv', 'a+')
                csv.write('#date')

                lock.acquire()
                idx = 1
                for s in sensors:
                    if s.enabled:
                        s.used = idx
                        idx += 1
                        csv.write(',' + s.name)
                    else: s.used = 0
                lock.release()

                csv.write('\n')
                csv.close()
                sync()
                config['active'] = nc['active']
                config['brewfiles'].append(config['active'])

        if 'running' in nc: config['running'] = nc['running']
        if 'update' in nc: config['update'] = int(nc['update'])
        if 'sync' in nc: config['sync'] = int(nc['sync'])
        if 'debug' in nc: config['debug'] = nc['debug']
        if 'decimate' in nc: config['decimate'] = nc['decimate']
        if 'date' in nc:
            try:
                datetime.datetime.strptime(nc['date'], '%Y/%m/%d %H:%M:%S')
                subprocess.call(['date', '-s', nc['date']])
            except:
                self.send_error(500, 'Bad date format!')
                print('bad date passed: ' + nc['date'])
                return
        store_config()
        event.set()
        self.sendStatus()

    def handleFile(self):
        mime = {
            '.csv': 'text/html',
            '.html': 'text/html',
            '.map':  'application/json',
            '.jpg': 'image/jpg',
            '.gif': 'image/gif',
            '.js': 'application/javascript',
            '.css': 'text/css',
        }
        ext = self.path[self.path.rfind('.'):]
        if debug: print('ext: ' + ext)

        if not ext in mime:
            m = 'text/html'
            print('extension not found: ' + ext)
        else: m = mime[ext]
        if ext == '.csv': sync()

        fn = curdir + sep + self.path
        try:
            ft = os.path.getmtime(fn)
            if self.headers.get('If-Modified-Since'):
                ts = datetime.datetime(*eut.parsedate(self.headers.get('If-Modified-Since'))[:6])
                if ts >= datetime.datetime.utcfromtimestamp(round(ft)):
                    self.send_response(304)
                    self.end_headers()
                    return

            f = open(fn)
            self.send_response(200)
            self.send_header('Content-type', m)
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Last-Modified', self.date_time_string(ft))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(gzip.compress(bytearray(f.read(), 'utf-8')))
            f.close()
            return
        except IOError:
            self.send_error(404,'File Not Found: %s' % self.path)
        except:
            self.send_error(500,'Unknown error: %s' % sys.exc_info()[0])

    def handleData(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        d = ''
        for f in listdir(datadir):
            d += '<a href="' + f + '">' + f + '</a><br>'
        self.wfile.write(bytearray(d, 'utf-8'))

threading.Thread(daemon=True, target=thread_temp).start()
if shutdown_pin != None: threading.Thread(daemon=True, target=thread_shutdown).start()
threading.Thread(daemon=True, target=thread_discovery).start()

def signal_term_handler(signal, frame):
    print('got SIGTERM')
    sync()
    sys.exit(0)
signal.signal(signal.SIGTERM, signal_term_handler)

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    pass

try:
    server = ThreadingHTTPServer(('', PORT_NUMBER), BrewHTTPHandler)
    server.daemon_threads = True
    print ('Started httpserver on port ' , PORT_NUMBER)
    server.serve_forever()
except KeyboardInterrupt:
    print('^C received, shutting down the web server')
    sync()
    server.socket.close()

