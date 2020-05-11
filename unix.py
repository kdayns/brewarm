#!/usr/bin/env python3

import threading;
import subprocess;
import signal
import os
from os import listdir, path
import http.server
import socketserver
import datetime;
from threading import Timer

import w1dev
import cfg
import brewarm
from w1dev import w1d

lcd = None
shutdown_pin    = None # gpio pin number 7

def thread_shutdown():
    try: open('/sys/class/gpio/export', 'w').write(str(shutdown_pin))
    except: print('export failed: ' + str(sys.exc_info()[0]))

    while True:
        val = ''
        try: val = open('/sys/class/gpio/gpio%u/value' % shutdown_pin).read().strip()
        except: print('gpio open failed: ' + str(sys.exc_info()[0]))
        if val == '1':
            print('shutdown')
            if cfg.config['sync']: sync()
            open('.clean_shutdown', 'w').close()
            subprocess.call(['shutdown', '-h', 'now'])
            return;
        threading.Event().wait(timeout=5)

    #Timer(5, thread_shutdown, ()).start()
    return

def thread_discovery():
    while True:
        # monitor w1
        found = False
        for f in listdir(w1dev.w1path):
            if f == 'w1_bus_master1': continue
            if not path.isdir(w1dev.w1path + '/' + f): continue

            s = cfg.getSensor(f)
            if s is None:
                print("new sensor: " + f)
                found = True
                cfg.acquire()
                cfg.sensors.append(w1d(f))
                cfg.release()

        if found:
            cfg.store_config()
            cfg.event.set()

        threading.Event().wait(timeout=5)
    #Timer(5, thread_discovery, ()).start()
    return

def read_all(now, lastRead):
    rthreads = []

    t = not w1dev.sw_ds18b20
    # threaded reading works faster
    cfg.acquire()
    for s in cfg.sensors:
        if s.isTemp():
            if not t: brewarm.task_update_temp(s)
            else:
                th = threading.Thread(daemon=True, target=brewarm.task_update_temp, args=(s,))
                th.start()
                rthreads.append(th)
    if t:
        for th in rthreads: th.join()
    cfg.release()

    mt = cfg.getMainTemp()
    if cfg.isRunning():
        cfg.acquire()
        for s in cfg.sensors:
            if s.isSwitch():
                if lastRead is not None: s.pid(mt, (now - lastRead).total_seconds())
                else: s.pid(mt, 0)
                s.read()
                print("state: " + str(s.curr))
        cfg.release()

    if lcd is not None:
        s = cfg.getMainSensor()
        if s is None:
                lcd.Clear()
        else:
                # TODO - negative numbers
                if s.avg is None: lcd.Clear()
                else:
                    la = [int(i) for i in list(str(round(s.avg, 2)).replace('.', ''))]
                    for i in range(4 - len(la)): la.append(0)
                    lcd.Show(la)

def thread_temp():
    sensors = cfg.sensors
    lastRead = None
    now = datetime.datetime.now()

    while True:
        beforeRead = now
        read_all(now, lastRead)
        lastRead = now
        now = datetime.datetime.now()
        print('-- reading sensors took: ' + str(now - beforeRead))

        brewarm.task_temp(now)

        if cfg.testmode:
            ch = False
            while not ch:
                cfg.acquire()
                for s in sensors:
                    ch |= s.changed()
                cfg.release()
                if not ch: threading.Event().wait(timeout=1)
            print("changed")
        else:
            cfg.event.wait(timeout=cfg.config['update'])
            cfg.event.clear()
    return

def init():
    print("unix init")

    if not cfg.testmode:
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

    if 0: # rpi lcd
        import tm1637
        lcd = tm1637.TM1637(16,15, tm1637.BRIGHT_HIGHEST)
        lcd.ShowDoublepoint(True)
        lcd.Clear()

    if 0: # hw clock
        open('/sys/class/i2c-adapter/i2c-' + str(cfg.config['i2c_bus']) + '/new_device', 'w').write("ds1307 0x68")
        subprocess.call(['hwclock', '-s']) # load clock from rtc

    #if shutdown_pin != None: Timer(0, thread_shutdown, ()).start()
    #Timer(5, thread_discovery, ()).start()
    if shutdown_pin != None: threading.Thread(daemon=True, target=thread_shutdown).start()
    threading.Thread(daemon=True, target=thread_discovery).start()
    threading.Thread(daemon=True, target=thread_temp).start()

    def signal_term_handler(signal, frame):
        print('got SIGTERM')
        sync()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_term_handler)

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    pass

cfg.init(threading.Lock(), threading.Event())
init()

try:
    server = ThreadingHTTPServer(('', cfg.PORT_NUMBER), brewarm.BrewHTTPHandler)
    server.daemon_threads = True
    print ('Started httpserver on port ' , cfg.PORT_NUMBER)
    server.serve_forever()
except KeyboardInterrupt:
    print('^C received, shutting down the web server')
    brewarm.sync()
    server.socket.close()
