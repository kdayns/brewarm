#!/bin/env python3

import sys
import json
import time
import http.server
import socketserver
from os import curdir, sep, listdir
import datetime;
import subprocess;
import threading;

# config
updateInterval  = 6
debug           = 1

datadir         = 'data'
PORT_NUMBER     = 8080
config = {
    'sensors'   : { 'xxxx': ['name', 1, 2]},
    'brewfiles' : [],
    'active'    : 'test',
    'running'   : False,
}

# private
#w1path = '/sys/bus/w1/devices/'
w1path = '/sys/bus/usb/devices/'
name = 0
curr = 1
avg = 2
lock = threading.Lock()

subprocess.call(['modprobe', 'w1-gpio', 'gpiopin=10'])
subprocess.call(['modprobe', 'w1_therm'])

def thread_update_temp(d):
    # TODO - read sensor
    return

def thread_temp():
    global config
    sensors = config['sensors']

    while True:
        lock.acquire()
        for k,d in sensors.items(): d[avg] = 0

        rthreads = []
        for k,d in sensors.items():
            th = threading.Thread(daemon=True, target=thread_update_temp, args=(d,))
            th.start()
            rthreads.append(th)
        lock.release()

        for th in rthreads:
            th.join()
        if debug: print('waiting: ', updateInterval)
        threading.Event().wait(timeout=updateInterval)

def thread_shutdown():
    while True:
        # TODO - monitor gpio
        # /sys/class/gpio
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
                sensors[f] = [ f, 0, 0]
            lock.release()
        if found: open('config', 'w').write(json.dumps(config))

        # monitor data dir
        for f in listdir('data'):
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
        varLen = int(self.headers['Content-Length'])
        postVars = str(self.rfile.read(varLen), 'utf-8')
        if debug:
            if len(postVars): print('post: ' + postVars)
            print(json.dumps(config))

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

