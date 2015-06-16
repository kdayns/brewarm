#!/bin/env python3

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
import tm1637

shutdown_pin    = 7
datadir         = 'data'
PORT_NUMBER     = 80
config = {
    'sensors'   : {},
    'active'    : '',
    'running'   : False,
    'update'    : 60,
    'decimate'  : 4,
    'debug'     : 1,
    'sync'      : 60 * 60,
    'i2c_bus'   : 1,
}

# private
lcd = None
csv = None
comment = None
latest = []
w1path = '/sys/bus/w1/devices/'
lock = threading.Lock()
event = threading.Event()
lastSync = datetime.datetime.now()

subprocess.call(['modprobe', 'w1-gpio', 'gpiopin=10'])
subprocess.call(['modprobe', 'w1_therm'])
subprocess.call(['hwclock', '-s']) # load clock from rtc
os.chdir('/root/brewarm')

lcd = tm1637.TM1637(16,15, tm1637.BRIGHT_HIGHEST)
lcd.ShowDoublepoint(True)
lcd.Clear()

def update_config():
    global debug, config

    debug = config['debug']
    configx = copy.deepcopy(config)
    print(json.dumps(configx, indent=True))
    if 'brewfiles' in configx: del configx['brewfiles']
    if 'date' in configx: del configx['date']
    if 'tail' in configx: del configx['tail']
    open('config', 'w').write(json.dumps(configx, indent=True))

if path.isfile('config'):
    config = json.loads(open('config').read())
    config['brewfiles'] = []
    if not 'lcd' in config: config['lcd'] = ''
    if not 'debug' in config: config['debug'] = True
    if not 'decimate' in config: config['decimate'] = 4
    if not 'sync' in config: config['sync'] = 60 * 60
    if not 'i2c_bus' in config: config['i2c_bus'] = 0
    open('/sys/class/i2c-adapter/i2c-' + str(config['i2c_bus']) + '/new_device', 'w').write("ds1307 0x68")
    if len(config['sensors']) and type(next(iter(config['sensors'].values()))) is not dict:
         s = {}
         for k,v in config['sensors'].items():
             s[k] = { 'name':v[0], 'curr':v[1], 'avg':v[2], 'enabled':v[3], 'min':-20, 'max':100 }
         config['sensors'] = s
    # drop unconfigured sensors
    config['sensors'] = { k : v for k,v in config['sensors'].items() if k != v['name'] }

if path.isfile('.clean_shutdown'):
    config['running'] = False
    update_config()
    os.remove('.clean_shutdown')

debug = config['debug']

def thread_update_temp(k, d):
    decimate = config['decimate']

    v = None
    for i in range(decimate):
        try: val = open(w1path + k + '/w1_slave').read()
        except:
            print('read sensor %s failed: %s ' % (k, str(sys.exc_info()[0])))
            # TODO - write empty reading
            d['curr'] = d['min']
            d['avg'] = d['min']
            return
        pos = val.find('t=')
        v = float(val[pos + 2:]) / 1000
        d['curr'] = min(max(round(v, 3), d['min']), d['max'])
        d['avg'] += d['curr']

    if v == None: v = 0
    if debug: print("data: %s %s " % (k, v))
    if config['lcd'] == k:
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
    global config, csv, event, latest, lastSync, comment
    sensors = config['sensors']
    lastActive = ''
    asens = []

    while True:
        lock.acquire()
        for k,d in sensors.items(): d['avg'] = 0

        rthreads = []
        for k,d in sensors.items():
            if not d['enabled']:
                d['curr'] = None
                continue
            th = threading.Thread(daemon=True, target=thread_update_temp, args=(k, d,))
            th.start()
            rthreads.append(th)
        lock.release()

        for th in rthreads: th.join()

        # write file
        if config['running'] == False:
            latest = []
            asens = []
            lastActive = ''
            if csv != None:
                csv.close()
                csv = None
                sync()
        else:
            if lastActive != config['active']:
                latest = []
                asens = []
                if csv != None:
                    csv.close()
                    sync()
                try:
                    if config['sync']:
                        sync(True)
                        csv = open('/tmp/' + config['active'], 'a+')
                    else: csv = open(datadir + '/' + config['active'] + '.csv', 'a+')
                    size = csv.tell()
                    if size:
                        print('appending: ' + config['active'])
                        # get used sensors
                        csv.seek(0, io.SEEK_SET)
                        l = csv.readline().strip()
                        if l[:6] != '#date,': raise
                        l = l[6:]
                        lock.acquire()
                        for s in l.split(','):
                            for k,d in sensors.items():
                                if s == d['name']:
                                    asens.append(k)
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
                    else:
                        lock.acquire()
                        for k,d in sensors.items():
                            if d['enabled']: asens.append(k)
                        lock.release()
                        print('new data file: ' + config['active'] + ' sensors: ' + str(len(asens)))
                        csv.write('#date')
                        for s in asens: csv.write(',' + sensors[s]['name'])
                        csv.write('\n')
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
                for s in asens:
                    if not sensors[s]['enabled']:
                        v = None
                        csv.write(',')
                    else:
                        v = round(sensors[s]['avg'] / config['decimate'], 3)
                        csv.write(',' + str(v))
                    newdata.append(v)

                if comment != None:
                    i = 0
                    for s in asens:
                        if sensors[s]['name'] != comment['sensor']:
                            i = i + 1
                            continue
                        csv.write(' #' + str(i) + ' ' + comment['string'])
                        i = i + 1
                        break
                    comment = None

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
    global config
    sensors = config['sensors']
    brews = config['brewfiles']

    while True:
        # monitor w1
        found = False
        for f in listdir(w1path):
            if f == 'w1_bus_master1': continue

            lock.acquire()
            if not f in sensors.keys():
                print("new sensor: " + f)
                found = True
                sensors[f] = { 'name':f, 'curr':0, 'avg':0, 'enabled':True, 'min':-20, 'max':100 }
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
        global config, latest
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        status = config
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
        else: self.handleConfig(postVars)

    def handleComment(self, postVars):
        global comment, config
        if comment != None:
            self.send_error(500,'Comment pending!')
            return

        if config['running'] == False:
            self.send_error(500,'Not running')
            return
        #TODO - check if sensor active

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

        post = json.loads(postVars)
        config['lcd'] = post['sensor']
        print('LCD sensor: ' + config['lcd'])

        update_config()
        event.set()

        if lcd == None: return

        if not lcd.connected():
            self.send_error(500,'Not connected!')
            return

        self.send_response(200)
        self.end_headers()
        return

    def handleRemove(self, postVars):
        global config
        post = json.loads(postVars)
        print('remove sensor: ' + post['sensor'])

        config['sensors'] = { k : v for k,v in config['sensors'].items() if k != post['sensor'] }
        update_config()

        self.send_response(200)
        self.end_headers()
        return

    def handleConfig(self, postVars):
        if debug:
            print('current config: ' + json.dumps(config))

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
            return;
        if 'sensors' in nc:
            lock.acquire()
            for k,v in nc['sensors'].items():
                if config['sensors'][k]['name'] != v[0]: config['sensors'][k]['name'] = v[0]
                if config['sensors'][k]['enabled'] != v[1]: config['sensors'][k]['enabled'] = v[1]
                if config['sensors'][k]['min'] != v[2]: config['sensors'][k]['min'] = int(v[2])
                if config['sensors'][k]['max'] != v[3]: config['sensors'][k]['max'] = int(v[3])
            lock.release()
        if 'lcd' in nc: config['lcd'] = nc['lcd']
        if 'active' in nc: config['active'] = nc['active']
        if 'running' in nc: config['running'] = nc['running']
        if 'update' in nc: config['update'] = int(nc['update'])
        if 'debug' in nc: config['debug'] = nc['debug']
        if 'decimate' in nc: config['decimate'] = nc['decimate']
        if 'date' in nc:
            try:
                datetime.datetime.strptime(nc['date'], '%Y/%m/%d %H:%M:%S')
                subprocess.call(['date', '-s', nc['date']])
            except: print('bad date passed: ' + nc['date'])
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

        try:
            f = open(curdir + sep + self.path) 
            self.send_response(200)
            self.send_header('Content-type', m)
            self.send_header('Content-Encoding', 'gzip')
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

