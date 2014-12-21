#!/bin/env python3

import sys
import json
import http.server
import socketserver
from os import curdir, sep
import datetime;
import subprocess;
import threading;

debug   = 1
root    = 'web'
PORT_NUMBER     = 8080

config = {
    'sensors': { 'xxxx': ['name', 1, 2]},
    'brewfiles': ["test"],
    'active': 'test',
}

def update_temp():
    return


#while True:
#    update_temp()
#sleep(updateInterval)



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

try:
    server = http.server.HTTPServer(('', PORT_NUMBER), myHandler)
    print ('Started httpserver on port ' , PORT_NUMBER)
    server.serve_forever()
except KeyboardInterrupt:
    print('^C received, shutting down the web server')
    server.socket.close()

