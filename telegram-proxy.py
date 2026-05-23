#!/usr/bin/env python3
"""
Telegram proxy for ESP32-C3 devices.

The ESP32-C3 (~400KB SRAM) cannot sustain WiFiClientSecure to
api.telegram.org:443 alongside HTTP LLM calls (Ollama, etc.).

This proxy accepts plain HTTP POST from the C3 and forwards to
api.telegram.org:443 over TLS, freeing ~55KB of heap.

Usage:
    python3 telegram-proxy.py [--port 9443]

Systemd service: telegram-proxy.service
"""

import http.server
import urllib.request
import sys
import os

PORT = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--port' else 9443
TG_API = "https://api.telegram.org"

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b''

        url = f"{TG_API}{self.path}"
        req = urllib.request.Request(
            url, data=body,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            body = f'{{"error":"{e}"}}'.encode()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

if __name__ == '__main__':
    server = http.server.HTTPServer(('0.0.0.0', PORT), ProxyHandler)
    print(f"Telegram proxy listening on 0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()