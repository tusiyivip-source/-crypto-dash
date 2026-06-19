#!/usr/bin/env python3
"""
牛牛盯盘系统 - 本地服务器 (含钉钉代理)
解决浏览器跨域 (CORS) 限制，转发钉钉消息请求。
"""
import http.server
import json
import socketserver
import urllib.request
import urllib.error
from urllib.parse import urlparse

PORT = 8081

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/proxy/dingtalk':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            # Extract target URL and headers from the body
            try:
                payload = json.loads(body)
                target_url = payload['url']
                target_body = payload.get('body', '{}')
            except Exception:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"Invalid payload"}')
                return

            req = urllib.request.Request(
                target_url,
                data=target_body.encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(data)
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(e.read() or b'{}')
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error":"Not found"}')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[proxy] {args[0]}")

if __name__ == '__main__':
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"牛牛服务已启动: http://localhost:{PORT}")
        print(f"局域网访问: http://<本机IP>:{PORT}")
        print(f"钉钉代理已就绪: POST /proxy/dingtalk")
        httpd.serve_forever()
