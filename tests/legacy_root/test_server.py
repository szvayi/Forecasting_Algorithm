#!/usr/bin/env python3
"""
简单的HTTP服务器测试
"""
import http.server
import socketserver
import threading

PORT = 8001

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        else:
            super().do_GET()

def start_server():
    print(f"启动HTTP服务器在端口 {PORT}...")
    Handler = MyHTTPRequestHandler
    
    try:
        with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
            print(f"服务器运行在 http://0.0.0.0:{PORT}/")
            httpd.serve_forever()
    except Exception as e:
        print(f"服务器启动失败: {e}")

if __name__ == "__main__":
    # 启动服务器
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # 保持主进程运行
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("服务器已停止")
