#!/bin/env python3

import sys
import io
import json
import time
import http.server
import socketserver
from os import curdir, sep, listdir, path
import datetime;
import subprocess;
import threading;

# config
updateInterval  = 6
decimate        = 4
debug           = 1

shutdown_pin    = 7
datadir         = 'data'
PORT_NUMBER     = 8080
config = {
    'sensors'   : {},
    'brewfiles' : [],
    'active'    : '',
    'running'   : False,
}

# private
csv = None
w1path = '/sys/bus/w1/devices/'
name = 0
curr = 1
avg = 2
enabled = 3
lock = threading.Lock()

subprocess.call(['modprobe', 'w1-gpio', 'gpiopin=10'])
subprocess.call(['modprobe', 'w1_therm'])

if path.isfile('config'): config = json.loads(open('config').read())

def thread_update_temp(k, d):
    global decimate

    for i in range(decimate):
        try: val = open(w1path + k + '/w1_slave').read()
        except:
            print('read sensor %s failed: %s ' % (k, str(sys.exc_info()[0])))
            continue
        pos = val.find('t=')
        v = float(val[pos + 2:]) / 1000
        d[curr] = v
        d[avg] += d[curr]

    if debug: print("data: %s %s " % (k, v))
    return

def thread_temp():
    global config, csv
    sensors = config['sensors']
    lastActive = ''
    asens = []

    while True:
        lock.acquire()
        for k,d in sensors.items(): d[avg] = 0

        rthreads = []
        for k,d in sensors.items():
            th = threading.Thread(daemon=True, target=thread_update_temp, args=(k, d,))
            th.start()
            rthreads.append(th)
        lock.release()

        for th in rthreads: th.join()

        # write file
        if config['running'] == False:
            asens = []
            lastActive = ''
            if csv != None:
                csv.close()
                csv = None
        else:
            if lastActive != config['active']:
                if csv != None: csv.close()
                try:
                    csv = open(datadir + '/' + config['active'] + '.csv', 'a+')
                    if csv.tell():
                        print('appending: ' + config['active'])
                        csv.seek(0, io.SEEK_SET)
                        l = csv.readline().strip()
                        if l[:6] != '#date,': raise
                        l = l[6:]
                        csv.seek(0, io.SEEK_END)
                        # TODO date recovery
                        lock.acquire()
                        for k,d in sensors.items():
                            for s in l.split(','):
                                if s == d[name]:
                                    asens.append(k)
                                    break
                        lock.release()
                    else:
                        print('new data file: ' + config['active'])
                        lock.acquire()
                        for k,d in sensors.items():
                            if d[enabled]: asens.append(k)
                        lock.release()
                        csv.write('#date')
                        for s in asens: csv.write(',' + sensors[s][name])
                        csv.write('\r\n')
                    lastActive = config['active']
                except:
                    raise
                    print('csv open failed: ' + str(sys.exc_info()[0]))
                    if csv != None:
                        csv.close()
                        csv = None

            if csv != None:
                csv.write(datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S'))
                for s in asens: csv.write(',' + str(sensors[s][avg] / decimate))
                csv.write('\r\n')
                csv.flush()

        if debug: print('waiting: ', updateInterval)
        threading.Event().wait(timeout=updateInterval)

def thread_shutdown():
    try: open('/sys/class/gpio/export', 'w').write(str(shutdown_pin))
    except: print('export failed: ' + str(sys.exc_info()[0]))

    while True:
        try: val = open('/sys/class/gpio%u/value' % shutdown_pin).readline().strip()
        except: print('gpio open failed: ' + str(sys.exc_info()[0]))
        # TODO - monitor gpio
        #if val == '1': subprocess.call(['shutdown', '-h', 'now'])
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
                sensors[f] = [ f, 0, 0, True]
            lock.release()
        if found: open('config', 'w').write(json.dumps(config))

        # monitor data dir
        for f in listdir('data'):
            if not f.endswith('.csv'): continue
            f = f[:-4]
            if not f in brews: brews.append(f)

        threading.Event().wait(timeout=5)
    return

class myHandler(http.server.BaseHTTPRequestHandler):
    def handle_one_request(self):
        try:
            http.server.BaseHTTPRequestHandler.handle_one_request(self)
        except:
            if debug: raise
            else: print('Unknown error: %s' % sys.exc_info()[0])

    def do_POST(self):
        global config
        varLen = int(self.headers['Content-Length'])
        postVars = str(self.rfile.read(varLen), 'utf-8')
        if len(postVars):
            if debug:
                print('post: ' + postVars)
                print('config: ' + json.dumps(config))
            nc = json.loads(postVars)
            lock.acquire()
            for k,v in nc.items():
                if config['sensors'][k][name] != v: config['sensors'][k][name] = v
            lock.release()
            if 'active' in nc: config['active'] = nc['active']
            if 'running' in nc: config['running'] = nc['running']
            # TODO - new brew creation
            config['active'] = 'xxx'
            config['running'] = True
            open('config', 'w').write(json.dumps(config))

        self.send_response(200)
        self.end_headers()
        self.wfile.write(bytearray(json.dumps(config), 'utf-8'))

    def do_GET(self):
        if self.path=="/": self.path="/index.html"

        print(self.path)
        mime = {
            '.html': 'text/html',
            '.jpg': 'image/jpg',
            '.gif': 'image/gif',
            '.js': 'application/javascript',
            '.css': 'text/css',
        }
        ext = self.path[self.path.rfind('.'):]
        if debug: print('ext: ' + ext)

        if not ext in mime: m = 'text/html'
        else: m = mime[ext]

        try:
            f = open(curdir + sep + self.path) 
            self.send_response(200)
            self.send_header('Content-type', m)
            self.end_headers()
            self.wfile.write(bytearray(f.read(), 'utf-8'))
            f.close()
            return
        except IOError:
            self.send_error(404,'File Not Found: %s' % self.path)
        except:
            self.send_error(500,'Unknown error: %s' % sys.exc_info()[0])

threading.Thread(daemon=True, target=thread_temp).start()
threading.Thread(daemon=True, target=thread_shutdown).start()
threading.Thread(daemon=True, target=thread_discovery).start()

try:
    server = http.server.HTTPServer(('', PORT_NUMBER), myHandler)
    print ('Started httpserver on port ' , PORT_NUMBER)
    server.serve_forever()
except KeyboardInterrupt:
    print('^C received, shutting down the web server')
    server.socket.close()

