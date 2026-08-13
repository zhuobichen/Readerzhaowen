# -*- coding: utf-8 -*-
"""HTTP 服务器入口。"""
import sys
from http.server import ThreadingHTTPServer

from .constants import BOOKS_DIR
from .routes import Handler

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    port = 8769
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    srv = Server(("0.0.0.0", port), Handler)
    print(f"书架阅读器已启动:  http://localhost:{port}")
    print(f"书籍目录: {BOOKS_DIR}")
    print("按 Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()

