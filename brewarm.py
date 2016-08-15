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
from w1d import w1d

shutdown_pin    = 7
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
w1path = '/sys/bus/w1/devices/'
lock = threading.Lock()
event = threading.Event()
lastSync = datetime.datetime.now()

subprocess.call(['modprobe', 'w1-gpio', 'gpiopin=10'])
subprocess.call(['modprobe', 'w1_therm'])
subprocess.call(['modprobe', 'w1_ds2413'])
os.chdir('/root/brewarm')

def update_config():
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
    config['sensors'] = { k : v for k,v in config['sensors'].items() if k != v['name'] }

    for k,v in config['sensors'].items():
        sensors.append(w1d(k, v))

    sensors.sort(key=lambda s: s.id, reverse=True)
    del config['sensors']

if path.isfile('.clean_shutdown'):
    config['running'] = False
    update_config()
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

    v = None
    for i in range(decimate):
        v = s.read()
        if v is None:
            # TODO - write empty reading
            s.avg = s.min
            v = 0
            break
        s.avg += s.curr

    if debug: print("data: %s %s " % (s.id, v))
    if lcd is not None and config['lcd'] == k:
        # TODO - negative numbers
        la = [int(i) for i in list(str(round(v, 2)).replace('.', ''))]
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

def thread_temp():
    global config, sensors, csv, event, latest, lastSync, comment
    lastActive = ''

    while True:
        rthreads = []
        lock.acquire()
        for s in sensors:
            if s.isSwitch():
                s.read()
                print("state: " + str(s.curr))
            elif s.isTemp():
                s.avg = 0
                if not s.enabled:
                    s.curr = None
                    continue
                th = threading.Thread(daemon=True, target=thread_update_temp, args=(s,))
                th.start()
                rthreads.append(th)
        lock.release()

        for th in rthreads: th.join()

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
                        if last > datetime.datetime.now():
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
                now = datetime.datetime.now()
                newdata.append(int(now.timestamp() * 1000))
                csv.write(now.strftime('%Y/%m/%d %H:%M:%S'))

                lock.acquire()
                ssens = copy.deepcopy(sensors)
                ssens.sort(key=lambda s: s.used)
                for s in ssens:
                    if not s.used: continue
                    if not s.enabled:
                        v = None
                        csv.write(',')
                        continue

                    if s.isSwitch():
                        if s.curr:
                            v = 1
                            csv.write(',true')
                        else:
                            v = 0
                            csv.write(',false')
                    elif s.isTemp():
                        v = round(s.avg / config['decimate'], 3)
                        csv.write(',' + str(v))
                    newdata.append(v)

                if comment != None:
                    i = 0
                    for s in sensors:
                        if s.name != comment['sensor']:
                            i = i + 1
                            continue
                        csv.write(' #' + str(i) + ' ' + comment['string'])
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
        threading.Event().wait(timeout=1)
    return

def thread_discovery():
    global config, sensors
    brews = config['brewfiles']

    while True:
        # monitor w1
        found = False
        for f in listdir(w1path):
            if f == 'w1_bus_master1': continue

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
            update_config()
            event.set()

        # monitor data dir
        for f in listdir('data'):
            if not f.endswith('.csv'): continue
            f = f[:-4]
            if not f in brews: brews.append(f)

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
        elif self.path == '/lcd': self.handleLCD(postVars)
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

        lock.acquire()
        active = False
        for s in sensors:
            if s.id == post['sensor']:
                active = s.used
                break
        lock.release()

        if active == False:
            self.send_error(500,'Sensor not used in current brew!')
            return

        post = json.loads(postVars)
        comment = {}
        comment['sensor'] = post['sensor']
        comment['string'] = post['comment']
        event.set()

        self.send_response(200)
        self.end_headers()
        return

    def handleLCD(self, postVars):
        global lcd, config

        if lcd == None:
            self.send_error(500, 'Not present!')
            return

        post = json.loads(postVars)
        config['lcd'] = post['sensor']
        print('LCD sensor: ' + config['lcd'])

        update_config()
        event.set()

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

        update_config()

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
                    break;
            lock.release()

        if 'lcd' in nc: config['lcd'] = nc['lcd']
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
        update_config()
        event.set()
        self.sendStatus()

    def handleFile(self):
        mime = {
            '.csv': 'text/html',
            '.html': 'text/html',
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

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    pass

threading.Thread(daemon=True, target=thread_temp).start()
threading.Thread(daemon=True, target=thread_shutdown).start()
threading.Thread(daemon=True, target=thread_discovery).start()

def signal_term_handler(signal, frame):
    print('got SIGTERM')
    sync()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_term_handler)

try:
    server = ThreadingHTTPServer(('', PORT_NUMBER), BrewHTTPHandler)
    server.daemon_threads = True
    print ('Started httpserver on port ' , PORT_NUMBER)
    server.serve_forever()
except KeyboardInterrupt:
    print('^C received, shutting down the web server')
    sync()
    server.socket.close()

