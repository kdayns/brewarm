#!/usr/bin/env python3

import gzip
import sys
import copy
import io
import os
import time
import shutil;
import json;
import http.server
from os import curdir, sep, listdir, path
import email.utils as eut
import datetime;
import subprocess;

import cfg

lastActive = ''
lastSync = datetime.datetime.now()
latest = []
comment = None
csv = None

def task_update_temp(s):
    if not s.enabled:
        s.avg = None
        s.curr = None
        return

    s.avg = 0
    cnt = 0
    retried = False
    for i in range(cfg.config['decimate']):
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
    if cfg.debug: print("data: %s %s %d" % (s.id, s.avg, cnt))

def sync(toTemp = False):
    print('syncing.. ' + str(toTemp))
    f = cfg.datadir + '/' + cfg.config['active'] + '.csv'
    t = '/tmp/' + cfg.config['active']
    if toTemp:
        if path.isfile(f): shutil.copyfile(f, t)
    else:
        if path.isfile(t):
            shutil.copyfile(t, f + '_tmp')
            shutil.move(f + '_tmp', f)
        else:
            print("temp not present")

def task_temp(now):
        global lastSync, lastActive
        global csv, latest, comment

        config = cfg.config

        # write file
        if not cfg.isRunning():
            latest = []
            lastActive = ''
            if csv != None:
                csv.close()
                csv = None
                cfg.unuseSensors()
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
                    else: csv = open(cfg.datadir + '/' + config['active'] + '.csv', 'a+')
                    size = csv.tell()

                    print('appending: ' + config['active'])
                    # get used sensors
                    csv.seek(0, io.SEEK_SET)
                    l = csv.readline().strip()
                    if l[:6] != '#date,': raise
                    l = l[6:]

                    cfg.unuseSensors()
                    idx = 1
                    cfg.acquire()
                    for item in l.split(','):
                        for s in cfg.sensors:
                            if s.name == item:
                                s.used = idx
                                idx += 1
                                break
                    cfg.release()

                    # date recovery
                    csv.seek(size - min(128, size), io.SEEK_SET)
                    tail = csv.read(128)
                    if len(tail) > 5 and tail.rfind('\n', 0, -2) != -1:
                        tail = tail[tail.rfind('\n', 0, -2) + 1:].strip()
                        if cfg.debug: print('tail: ' + tail)
                        tail = tail[:tail.find(',')]
                        last = datetime.datetime.strptime(tail, '%Y/%m/%d %H:%M:%S')
                        if cfg.debug: print('last: ' + str(last))
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

                ssens = cfg.getSensorView()
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
                        # pid out
                        csv.write(',')
                        pv = s.get()
                        if pv is not None:
                            csv.write(str(round(pv, 3)))
                        newdata.append(pv)
                    elif s.isTemp():
                        v = s.avg
                        if s.avg is not None: csv.write(str(v))
                    # TODO - none
                    #if v is None:
                    newdata.append(v)

                if comment != None:
                    s = cfg.getSensorByName(comment['sensor'])
                    if s is not None:
                        csv.write(' #' + str(s.used - 1) + ' ' + comment['string'])
                    comment = None

                csv.write('\n')
                csv.flush()
                latest.append(newdata)
                if len(latest) > 10: latest.pop(0)
                if config['sync'] and (now - lastSync).total_seconds() > config['sync']:
                    lastSync = now
                    sync()

        if cfg.debug: print('waiting: ', config['update'])


class BrewHTTPHandler(http.server.BaseHTTPRequestHandler):
    def sendStatus(self):
        global latest
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

        status = copy.deepcopy(cfg.config)
        status['sensors'] = []
        for s in cfg.getSensorView():
            status['sensors'].append(s.dict())
        status['tail'] = latest
        status['date'] = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
        self.wfile.write(bytearray(json.dumps(status), 'utf-8'))

    def log_message(self, format, *args):
        if not cfg.debug: return
        http.server.BaseHTTPRequestHandler.log_message(self, format, *args)

    def handle_one_request(self):
        try:
            http.server.BaseHTTPRequestHandler.handle_one_request(self)
        except:
            if cfg.debug: raise
            else: print('Unknown error: %s' % sys.exc_info()[0])

    def do_GET(self):
        if self.path=="/": self.path="/index.html"

        if self.path=="/data/": self.handleData()
        else: self.handleFile()

    def do_POST(self):
        varLen = int(self.headers['Content-Length'])
        postVars = str(self.rfile.read(varLen), 'utf-8')

        if not len(postVars):
            self.sendStatus()
            return;

        if cfg.debug:
            print('post: ' + postVars)

        j = json.loads(postVars)
        if self.path == '/comment': self.handleComment(j)
        elif self.path == '/main': self.handleMain(j)
        elif self.path == '/command': self.handleCommand(j)
        elif self.path == '/remove': self.handleRemove(j)
        elif self.path == '/toggle': self.handleToggle(j)
        else: self.handleConfig(j)

    def handleComment(self, post):
        global comment
        if comment != None:
            self.send_error(500,'Comment pending!')
            return

        if not cfg.isRunning():
            self.send_error(500,'Not running')
            return

        s = cfg.getSensorByName(post['sensor'])
        if s is None or not s.enabled:
            self.send_error(500,'Sensor not used in current brew!')
            return

        comment = {}
        comment['sensor'] = post['sensor']
        comment['string'] = post['comment']

        self.send_response(200)
        self.end_headers()

        cfg.event.set()
        return

    def handleMain(self, post):
        cfg.updateMainSensor(post['sensor'])

        self.send_response(200)
        self.end_headers()

        cfg.event.set()
        return

    def handleRemove(self, post):
        cfg.removeSensor(post['sensor'])
        self.send_response(200)
        self.end_headers()
        return

    def handleToggle(self, post):
        print('toggle sensor: ' + post['sensor'])

        s = cfg.getSensor(post['sensor'])
        if s is not None:
            s.force(post['force'])
            s.write(post['value'], post['force'])
            s.read()

        self.send_response(200)
        self.end_headers()

    def handleCommand(self, nc):
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
        else:
            self.send_response(500, 'no command')
        self.end_headers()

    def handleConfig(self, nc):
        config = cfg.config

        if cfg.debug: print('current config: ' + json.dumps(config))

        if 'sensors' in nc:
            for k,v in nc['sensors'].items():
                s = cfg.getSensor(k)
                if s != None:
                    cfg.acquire()
                    if cfg.debug: print('updating ' + s.name + ' ' + json.dumps(v))
                    if s.name != v[0]: s.name = v[0]
                    if s.enabled != v[1]: s.enabled = v[1]

                    if s.isTemp():
                        if s.min != v[2]: s.min = int(v[2])
                        if s.max != v[3]: s.max = int(v[3])
                    elif s.isSwitch():
                        # override state if s.state != v[2]: s.state = int(v[2])
                        s.setpoint = float(v[3])
                        s.mode = int(v[4])
                    cfg.release()
        cfg.updateMainSensor(None)

        #if 'main' in nc: config['main'] = nc['main']
        if 'active' in nc and config['active'] != nc['active']:
                print('new data file: ' + nc['active'])

                if config['sync']:
                    sync(True)
                    csv = open('/tmp/' + nc['active'], 'a+')
                else: csv = open(cfg.datadir + '/' + nc['active'] + '.csv', 'a+')
                csv.write('#date')

                cfg.acquire()
                idx = 1
                for s in cfg.sensors:
                    if s.enabled:
                        s.used = idx
                        idx += 1
                        csv.write(',' + s.name)
                        if s.isSwitch(): csv.write(',' + s.name + '_pid')
                    else: s.used = 0
                cfg.release()

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

        cfg.store_config()
        cfg.event.set()
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
        if cfg.debug: print('ext: ' + ext)

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
        for f in listdir(cfg.datadir):
            d += '<a href="' + f + '">' + f + '</a><br>'
        self.wfile.write(bytearray(d, 'utf-8'))
