# -*- coding: utf-8 -*-
"""书源工具桌面版入口。

- 开发模式:  python desktop/run.py [--port 8756] [--no-browser]
- 打包后:    双击 exe 即启动并自动打开浏览器

引擎模块在 standalone_build/（与打包布局一致）。
"""
import argparse
import os
import sys
import threading
import webbrowser

if getattr(sys, "frozen", False):
    BASE = sys._MEIPASS
    WEB_DIR = os.path.join(BASE, "web")
else:
    BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "standalone_build")
    WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
sys.path.insert(0, BASE)

import server  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="MyBooks 书源工具（桌面版）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    ap.add_argument("--port", type=int, default=8756, help="端口（默认 8756，被占用时自动换）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    server.set_web_dir(WEB_DIR)
    srv = server.create_server(args.host, args.port)
    port = srv.server_address[1]
    url = f"http://{args.host}:{port}/"

    print("=" * 56)
    print("  MyBooks 书源工具（桌面版）")
    print(f"  地址:  {url}")
    print(f"  数据:  {server.DATA_DIR}")
    print(f"  EPUB: {server.get_books_dir()}")
    print("  按 Ctrl+C 退出")
    print("=" * 56)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
