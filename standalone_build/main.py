"""
MyBooks Book Source — 独立 Web + CLI 版
"""

import argparse
import base64
import concurrent.futures
import http.server
import io
import json
import logging
import os
import re
import socketserver
import sys
import threading
import urllib.parse
import uuid
import zipfile

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Determine source path: next to EXE, then Desktop, then CWD
_EXE_DIR = os.path.dirname(os.path.abspath(__file__))
_DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
for _p in [
    os.path.join(_EXE_DIR, "sources.json"),
    os.path.join(_DESKTOP, "sources.json"),
    os.path.join(os.getcwd(), "sources.json"),
]:
    if os.path.exists(_p):
        DEFAULT_SOURCE = _p
        break
else:
    DEFAULT_SOURCE = os.path.join(_DESKTOP, "sources.json")

# ── 后台搜索会话 ──
_search_sessions: dict = {}
_session_lock = threading.Lock()


# ── source helpers ────────────────────────────────────────────────────────

def _load_all(source_path):
    from book_source_model import load_sources_from_json
    if not os.path.exists(source_path):
        return []
    return load_sources_from_json(source_path)


def _save_all(source_path, sources):
    from book_source_model import dump_sources_to_json
    dump_sources_to_json(sources, source_path)


def load_source(source_path, index=0):
    sources = _load_all(source_path)
    if index < 0 or index >= len(sources):
        return None
    return sources[index]


def _merge_sources(source_path, incoming):
    """Merge incoming data (dict or list) into existing sources, dedup by URL."""
    from book_source_model import BookSource
    sources = _load_all(source_path)

    items = incoming if isinstance(incoming, list) else [incoming]
    known_urls = {s.bookSourceUrl for s in sources if s.bookSourceUrl}

    added = 0
    for item in items:
        if not isinstance(item, dict) or not item.get("bookSourceName"):
            continue
        url = item.get("bookSourceUrl", "")
        # Use name as dedup key if no URL
        key = url or item.get("bookSourceName", "")
        if key and key in known_urls:
            continue
        src = BookSource.from_dict(item)
        src.enabled = True
        sources.append(src)
        if key:
            known_urls.add(key)
        added += 1

    if added:
        _save_all(source_path, sources)

    return {"ok": True, "added": added, "total": len(sources)}


# ── API ───────────────────────────────────────────────────────────────────

def api_sources(source_path):
    sources = _load_all(source_path)
    return [{"index": i, "name": s.bookSourceName, "url": s.bookSourceUrl,
             "group": s.bookSourceGroup, "enabled": s.enabled}
            for i, s in enumerate(sources)]


def api_source_detail(source_path, index):
    sources = _load_all(source_path)
    if index < 0 or index >= len(sources):
        return None
    d = sources[index].to_dict()
    d["index"] = index
    return d


def api_source_add(source_path, data):
    from book_source_model import BookSource
    sources = _load_all(source_path)
    src = BookSource.from_dict(data)
    src.enabled = True
    sources.append(src)
    _save_all(source_path, sources)
    return {"ok": True, "index": len(sources) - 1, "name": src.bookSourceName}


def api_source_update(source_path, index, data):
    from book_source_model import BookSource
    sources = _load_all(source_path)
    if index < 0 or index >= len(sources):
        return {"ok": False, "error": "索引无效"}
    src = BookSource.from_dict(data)
    src.enabled = True
    sources[index] = src
    _save_all(source_path, sources)
    return {"ok": True, "name": src.bookSourceName, "index": index}


def api_source_delete(source_path, index):
    sources = _load_all(source_path)
    if index < 0 or index >= len(sources):
        return {"ok": False, "error": "索引无效"}
    removed = sources.pop(index)
    _save_all(source_path, sources)
    return {"ok": True, "name": removed.bookSourceName}


def api_import_url(source_path, url):
    try:
        import requests
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        })
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"ok": False, "error": f"获取失败: {e}"}
    return _merge_sources(source_path, data)


def api_import_json(source_path, content):
    try:
        data = json.loads(content)
    except Exception as e:
        return {"ok": False, "error": f"JSON 解析失败: {e}"}
    return _merge_sources(source_path, data)


def api_import_zip(source_path, b64_content):
    try:
        raw = base64.b64decode(b64_content)
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as e:
        return {"ok": False, "error": f"ZIP 解析失败: {e}"}

    all_items = []
    for name in zf.namelist():
        if not name.endswith(".json"):
            continue
        try:
            content = zf.read(name).decode("utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                all_items.extend(data)
            elif isinstance(data, dict):
                all_items.append(data)
        except Exception:
            continue
    zf.close()

    if not all_items:
        return {"ok": False, "error": "ZIP 中未找到有效书源 JSON"}

    return _merge_sources(source_path, all_items)


def api_export(source_path):
    sources = _load_all(source_path)
    return [s.to_dict() for s in sources]


def _is_source_supported(src):
    """Check if source has basic compatibility with our engine."""
    search_url = (src.searchUrl or "").strip()
    # Skip sources using java.ajax in searchUrl (cannot emulate)
    if "java.ajax" in search_url or "<js>" in search_url:
        return False
    return True


def api_search(source_path, keyword, source_index=-1):
    """搜索（同步 — 单书源时直接调用；全书源时建议使用会话方式）"""
    from rule_engine import search_books
    src = load_source(source_path, source_index)
    if not src:
        return []
    results = search_books(src, keyword)
    for r in results:
        r["sourceName"] = src.bookSourceName
        r["sourceIndex"] = source_index
    return results


# ── 后台异步搜索（会话 + 轮询） ──

def api_search_start(source_path, keyword):
    """创建搜索会话，启动后台线程，立即返回 session_id"""
    session_id = uuid.uuid4().hex[:12]
    sources = _load_all(source_path)
    supported = [(si, src) for si, src in enumerate(sources)
                 if src.enabled and _is_source_supported(src)]
    skipped = [si for si, src in enumerate(sources)
               if src.enabled and not _is_source_supported(src)]

    session = {
        "status": "running",
        "keyword": keyword,
        "results": [],
        "total": len(supported),
        "completed": 0,
        "errors": [],
    }
    with _session_lock:
        _search_sessions[session_id] = session

    if skipped:
        logger.info("搜索 [%s] 跳过 %d 个不兼容书源", session_id, len(skipped))

    if not supported:
        session["status"] = "done"
        return {"session_id": session_id}

    t = threading.Thread(
        target=_search_worker,
        args=(session_id, supported, keyword),
        daemon=True,
    )
    t.start()
    return {"session_id": session_id}


def _search_worker(session_id, supported, keyword):
    """后台线程：并发搜索所有书源，逐次写入 session['results']"""
    from rule_engine import search_books

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        fut_to_info = {}
        for si, src in supported:
            f = pool.submit(search_books, src, keyword)
            fut_to_info[f] = (si, src)

        for f in concurrent.futures.as_completed(fut_to_info, timeout=300):
            si, src = fut_to_info[f]
            try:
                r = f.result()
                with _session_lock:
                    s = _search_sessions.get(session_id)
                    if s is None:
                        return
                    s["completed"] += 1
                    if r:
                        tagged = []
                        for item in r:
                            item["sourceName"] = src.bookSourceName
                            item["sourceIndex"] = si
                            tagged.append(item)
                        s["results"].extend(tagged)
                        logger.info("搜索成功 [%s] %s: %d 条",
                                    session_id, src.bookSourceName, len(r))
            except concurrent.futures.TimeoutError:
                with _session_lock:
                    s = _search_sessions.get(session_id)
                    if s:
                        s["completed"] += 1
                        s["errors"].append(f"{src.bookSourceName}: 超时")
                logger.warning("搜索超时 [%s] %s", session_id, src.bookSourceName)
            except Exception as e:
                with _session_lock:
                    s = _search_sessions.get(session_id)
                    if s:
                        s["completed"] += 1
                        s["errors"].append(f"{src.bookSourceName}: {e}")
                logger.warning("搜索失败 [%s] %s: %s", session_id, src.bookSourceName, e)

    with _session_lock:
        s = _search_sessions.get(session_id)
        if s:
            s["status"] = "done"
            logger.info("搜索完成 [%s]: %d/%d 书源, %d 条结果",
                        session_id, s["completed"], s["total"], len(s["results"]))


def api_search_progress(session_id):
    """获取搜索进度（结果按完整度排序，有书名+链接的优先）"""
    with _session_lock:
        s = _search_sessions.get(session_id)
    if s is None:
        return {"status": "not_found"}
    results = s["results"]
    # 排序：有name + bookUrl 的排最前，有name的次之，其余最后
    def _sort_key(item):
        name = bool(item.get("name"))
        url = bool(item.get("bookUrl"))
        return (0 if (name and url) else 1 if name else 2, item.get("name", "") or "")
    sorted_results = sorted(results, key=_sort_key)
    return {
        "status": s["status"],
        "results": sorted_results,
        "total": s["total"],
        "completed": s["completed"],
        "errors": s["errors"][-5:],
    }


def api_info(source_path, book_url, source_index=0):
    from rule_engine import fetch_book_info
    src = load_source(source_path, source_index)
    if not src:
        return {}
    return fetch_book_info(src, book_url) or {}


def api_toc(source_path, book_url, source_index=0):
    from rule_engine import fetch_toc
    src = load_source(source_path, source_index)
    if not src:
        return []
    return fetch_toc(src, book_url) or []


def api_download(source_path, book_url, keyword, source_index=0, max_chapters=9999):
    from rule_engine import fetch_book_info, fetch_toc, fetch_content
    from epub_helper import generate_epub
    src = load_source(source_path, source_index)
    if not src:
        return {"error": "书源无效"}
    if not book_url:
        return {"error": "书源未返回书籍链接，无法下载"}

    detail = fetch_book_info(src, book_url)
    toc = fetch_toc(src, book_url) or []
    chapters = []
    for i, entry in enumerate(toc[:max_chapters], 1):
        title = entry.get("title") or entry.get("chapterName") or f"第{i}章"
        url = entry.get("url") or entry.get("chapterUrl") or ""
        logger.info("下载 [%d/%d]: %s", i, min(max_chapters, len(toc)), title)
        content = fetch_content(src, url, title)
        if content:
            chapters.append({"title": title, "content": content})

    safe_name = re.sub(r'[\\/:*?"<>|]', '_', keyword)
    output = os.path.join(os.getcwd(), f"{safe_name}.epub")
    cover_url = (detail or {}).get("coverUrl", "")
    result = generate_epub(
        title=keyword, author=(detail or {}).get("author", "未知"),
        chapters=chapters, cover_url=cover_url, output_path=output,
    )
    return {"path": result, "chapters": len(chapters)}


# ── Web Server ────────────────────────────────────────────────────────────

HOST = "127.0.0.1"


class BookSourceHandler(http.server.BaseHTTPRequestHandler):

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _html(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _error(self, msg, status=400):
        self._json({"error": msg}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length).decode("utf-8") if length else ""

    def _sv(self):
        return getattr(self.server, "source_path", DEFAULT_SOURCE)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = dict(urllib.parse.parse_qsl(parsed.query))

        try:
            if path == "/" or path == "/index.html":
                return self._html(HTML_PAGE)

            if path == "/api/sources":
                return self._json(api_sources(self._sv()))

            if path == "/api/sources/export":
                return self._json(api_export(self._sv()))

            if path.startswith("/api/sources/"):
                parts = path.split("/")
                if len(parts) == 4 and parts[3].isdigit():
                    detail = api_source_detail(self._sv(), int(parts[3]))
                    if detail is None:
                        return self._error("not found", 404)
                    return self._json(detail)

            if path.startswith("/api/search/progress/"):
                sid = path.split("/")[-1]
                return self._json(api_search_progress(sid))

            if path == "/api/info":
                return self._json(api_info(self._sv(), qs.get("url", ""), int(qs.get("source_index", "0"))))

            if path == "/api/toc":
                return self._json(api_toc(self._sv(), qs.get("url", ""), int(qs.get("source_index", "0"))))

            self._error("not found", 404)
        except Exception as e:
            logger.exception("API GET 处理异常 [%s]", path)
            return self._error(f"服务器内部错误: {e}", 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return self._error("invalid JSON")

        try:
            if path == "/api/search/start":
                return self._json(api_search_start(self._sv(), data.get("keyword", "")))

            if path == "/api/search":
                return self._json(api_search(
                    self._sv(), data.get("keyword", ""),
                    int(data.get("source_index", "-1")),
                ))

            if path == "/api/download":
                return self._json(api_download(
                    self._sv(), data.get("bookUrl", ""), data.get("keyword", ""),
                    int(data.get("source_index", "0")),
                    int(data.get("max_chapters", "9999")),
                ))

            if path == "/api/sources/add":
                return self._json(api_source_add(self._sv(), data))

            if path == "/api/sources/update":
                return self._json(api_source_update(
                    self._sv(), int(data.get("index", "-1")), data,
                ))

            if path == "/api/sources/delete":
                return self._json(api_source_delete(self._sv(), int(data.get("index", "-1"))))

            if path == "/api/import/url":
                return self._json(api_import_url(self._sv(), data.get("url", "")))

            if path == "/api/import/json":
                return self._json(api_import_json(self._sv(), data.get("content", "")))

            if path == "/api/import/zip":
                return self._json(api_import_zip(self._sv(), data.get("file", "")))

            self._error("not found", 404)
        except Exception as e:
            logger.exception("API 处理异常 [%s]", path)
            return self._error(f"服务器内部错误: {e}", 500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        logger.info("HTTP %s", args[0] if args else "")


class ThreadedHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_web(source_path, port=0):
    sock = ThreadedHTTPServer((HOST, port), BookSourceHandler)
    host, actual_port = sock.server_address
    sock.source_path = source_path
    url = f"http://{host}:{actual_port}/"
    logger.info("Web 服务已启动: %s", url)

    import webbrowser
    webbrowser.open(url, new=2)

    try:
        sock.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务已停止")
        sock.shutdown()


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MyBooks Book Source", usage=argparse.SUPPRESS)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--port", type=int, default=0)

    sub = parser.add_subparsers(dest="command")

    p_search = sub.add_parser("search")
    p_search.add_argument("keyword")
    p_search.add_argument("--source-index", type=int, default=0)
    p_search.add_argument("--json", action="store_true")

    p_info = sub.add_parser("info")
    p_info.add_argument("bookUrl")
    p_info.add_argument("--source-index", type=int, default=0)

    p_toc = sub.add_parser("toc")
    p_toc.add_argument("bookUrl")
    p_toc.add_argument("--source-index", type=int, default=0)

    p_epub = sub.add_parser("epub")
    p_epub.add_argument("keyword")
    p_epub.add_argument("--max", type=int, default=9999)
    p_epub.add_argument("--source-index", type=int, default=0)

    sub.add_parser("sources")

    args = parser.parse_args()
    cmd = args.command

    if not cmd:
        print("正在启动 Web 界面... 按 Ctrl+C 退出")
        try:
            start_web(args.source, args.port)
        except KeyboardInterrupt:
            pass
        return

    if cmd == "search":
        r = api_search(args.source, args.keyword, args.source_index)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            for i, b in enumerate(r, 1):
                print(f"{i:3d}. {b.get('name','?'):30s} {b.get('author','?'):15s}")

    elif cmd == "info":
        r = api_info(args.source, args.bookUrl, args.source_index)
        for k, v in r.items():
            print(f"{k}: {v}")

    elif cmd == "toc":
        r = api_toc(args.source, args.bookUrl, args.source_index)
        for i, ch in enumerate(r, 1):
            print(f"{i:4d}. {ch.get('title','?')}")

    elif cmd == "epub":
        r = api_download(args.source, "", args.keyword, args.source_index, args.max)
        print(f"EPUB: {r.get('path', r.get('error','?'))} ({r.get('chapters',0)} 章)")

    elif cmd == "sources":
        for s in api_sources(args.source):
            print(f"{s['index']:3d}. {s['name']:30s} {s['url']}")


# ═══════════════════════════════════════════════════════════════════════════
# HTML 前端页面
# ═══════════════════════════════════════════════════════════════════════════

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>书源搜索</title>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js">
</script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans SC",sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
#app{max-width:960px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:8px}
h1 small{font-size:13px;font-weight:400;color:#64748b}
.tabs{display:flex;gap:0;margin-bottom:16px;border-radius:8px;overflow:hidden;border:1px solid #334155;width:fit-content}
.tab-btn{padding:8px 20px;cursor:pointer;border:none;font-size:14px;background:transparent;color:#94a3b8;transition:all .15s}
.tab-btn.active{background:#1e293b;color:#38bdf8;font-weight:600}
.tab-btn:hover{background:#1e293b}
.card{background:#1e293b;border-radius:10px;padding:16px;margin-bottom:14px;border:1px solid #334155}
label{display:block;font-size:13px;color:#94a3b8;margin-bottom:4px}
input,select,textarea{width:100%;padding:8px 12px;border:1px solid #475569;border-radius:6px;background:#0f172a;color:#e2e8f0;font-size:14px;outline:none;font-family:inherit}
input:focus,select:focus,textarea:focus{border-color:#38bdf8}
textarea{resize:vertical;min-height:60px}
.row{display:flex;gap:10px;align-items:end}
.row>*{flex:1}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:14px;font-weight:500;transition:opacity .15s;display:inline-flex;align-items:center;gap:4px}
.btn:hover{opacity:.85}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-primary{background:#2563eb;color:#fff}
.btn-success{background:#059669;color:#fff}
.btn-danger{background:#dc2626;color:#fff}
.btn-warning{background:#d97706;color:#fff}
.btn-sm{padding:5px 10px;font-size:12px}
.btn-outline{background:transparent;border:1px solid #475569;color:#94a3b8}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 6px;color:#64748b;font-weight:500;border-bottom:1px solid #334155;white-space:nowrap}
td{padding:8px 6px;border-bottom:1px solid #1e293b;vertical-align:middle}
tr:hover td{background:#0f172a}
.mono{font-family:monospace;font-size:12px;color:#64748b;word-break:break-all}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:#334155;color:#94a3b8}
.badge-ok{background:#064e3b;color:#34d399}
.badge-err{background:#450a0a;color:#f87171}
.badge-warn{background:#451a03;color:#fbbf24}
.mt-2{margin-top:8px}
.mb-2{margin-bottom:8px}
.mr-2{margin-right:8px}
.gap-2{gap:8px}
.flex{display:flex}
.flex-wrap{flex-wrap:wrap}
.items-center{align-items:center}
.justify-between{justify-content:space-between}
.text-center{text-align:center}
.text-sm{font-size:12px;color:#64748b}
.text-muted{color:#64748b}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid #475569;border-top-color:#38bdf8;border-radius:50%;animation:spin .6s linear infinite;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.empty{padding:30px 0;text-align:center;color:#64748b;font-size:14px}
.toast{position:fixed;top:16px;right:16px;padding:10px 18px;border-radius:8px;font-size:13px;z-index:999;max-width:400px;animation:slideIn .3s}
.toast-success{background:#064e3b;color:#34d399;border:1px solid #065f46}
.toast-error{background:#450a0a;color:#f87171;border:1px solid #7f1d1d}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
summary{cursor:pointer;font-weight:500;padding:4px 0;color:#94a3b8}
summary:hover{color:#e2e8f0}
details{margin-bottom:8px}
details[open]{padding-bottom:8px}
.import-zone{border:2px dashed #334155;border-radius:10px;padding:20px;text-align:center;cursor:pointer;transition:border-color .2s}
.import-zone:hover{border-color:#38bdf8}
.import-zone.dragover{border-color:#38bdf8;background:#1e3a5f}
.code-block{background:#0f172a;border-radius:6px;padding:12px;font-family:monospace;font-size:12px;white-space:pre-wrap;overflow-x:auto;max-height:400px;overflow-y:auto;border:1px solid #334155}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{background:#1e293b;border-radius:12px;padding:24px;max-width:720px;width:90%;max-height:85vh;overflow-y:auto;border:1px solid #334155}
.modal h2{font-size:18px;margin-bottom:8px}
.modal-close{float:right;background:none;border:none;color:#64748b;cursor:pointer;font-size:22px;line-height:1}
@media(max-width:640px){.row{flex-direction:column}}
</style>
</head>
<body>
<div id="app">
  <h1>书源搜索 <small>v1.1 — Web 管理 / 并发检索 / EPUB 下载</small></h1>

  <div class="tabs">
    <button class="tab-btn" :class="{active:tab==='search'}" @click="tab='search'">搜索下载</button>
    <button class="tab-btn" :class="{active:tab==='sources'}" @click="tab='sources'">书源管理</button>
    <button class="tab-btn" :class="{active:tab==='about'}" @click="tab='about'">关于</button>
  </div>

  <!-- ═══ Toast ═══ -->
  <div v-if="toast.show" class="toast" :class="'toast-'+toast.type">{{ toast.msg }}</div>

  <!-- ═══ 搜索页 ═══ -->
  <template v-if="tab==='search'">
    <div class="card">
      <div class="row">
        <div style="flex:3">
          <label>关键词</label>
          <input v-model="keyword" placeholder="书名 / 作者" @keyup.enter="doSearch">
        </div>
        <div style="flex:1">
          <label>搜索范围</label>
          <select v-model="searchSourceIndex">
            <option value="-1">全部书源</option>
            <option v-for="s in sources" :key="s.index" :value="s.index">{{ s.name }}</option>
          </select>
        </div>
        <div style="flex:none">
          <button class="btn btn-primary" @click="doSearch" :disabled="!keyword||searching">
            <span v-if="searching" class="spinner"></span>
            {{ searching ? '搜索中...' : '搜索' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 搜索进度 -->
    <div v-if="searching && searchProgress" class="card">
      <div class="flex items-center gap-2">
        <span class="spinner"></span>
        <span>搜索中... {{ searchProgress }}</span>
      </div>
    </div>

    <div v-if="results.length" class="card" style="padding:0;overflow:hidden">
      <div style="padding:10px 14px;border-bottom:1px solid #334155;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span>结果 ({{ results.length }})
          <template v-if="searching">— 已搜索 {{ searchProgress }}</template>
        </span>
        <button class="btn btn-sm btn-success" v-if="!downloading" @click="downloadAll">下载全部 EPUB</button>
      </div>
      <div style="overflow-x:auto">
        <table>
          <thead><tr>
            <th>书名</th><th>作者</th><th>最新章节</th><th>来源</th><th>操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="(b,i) in results" :key="i">
              <td><a :href="b.bookUrl" target="_blank" style="color:#38bdf8;text-decoration:none">{{ b.name || '?' }}</a></td>
              <td>{{ b.author || '?' }}</td>
              <td class="text-sm">{{ b.lastChapter || '' }}</td>
              <td><span class="badge">{{ b.sourceName || '?' }}</span></td>
              <td>
                <button class="btn btn-sm btn-success" @click="downloadOne(b)" :disabled="downloading">EPUB</button>
                <button class="btn btn-sm btn-outline" @click="showDetail(b)">详情</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="results.length===0 && searched && !searching && !searchProgress" class="empty">未找到结果</div>

    <!-- 下载进度 -->
    <div v-if="downloading" class="card">
      <div class="flex items-center gap-2">
        <span class="spinner"></span>
        <span>正在下载... {{ downloadStatus }}</span>
      </div>
    </div>

    <div v-if="downloadResult" class="card" style="border-color:#059669;display:flex;align-items:center;gap:8px">
      <span style="color:#34d399">&#10003;</span>
      <span>EPUB: <code>{{ downloadResult.path }}</code> ({{ downloadResult.chapters }} 章)</span>
      <button class="btn btn-sm btn-outline" @click="downloadResult=null">关闭</button>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detailBook" class="modal-overlay" @click.self="detailBook=null">
      <div class="modal">
        <button class="modal-close" @click="detailBook=null">&times;</button>
        <h2>{{ detailBook.name }}</h2>
        <div class="text-sm mb-2">{{ detailBook.author }} · {{ detailBook.sourceName }}</div>
        <table>
          <tr><td style="width:70px">封面</td><td><img :src="detailCover" style="max-height:150px" @error="detailCover=''" v-if="detailCover"></td></tr>
          <tr><td>简介</td><td>{{ detailIntro || '无' }}</td></tr>
          <tr><td>最新章节</td><td>{{ detailBook.lastChapter || '?' }}</td></tr>
          <tr><td>字数</td><td>{{ detailWordCount || '?' }}</td></tr>
        </table>
        <div class="mt-2" v-if="detailToc.length">
          <div style="font-weight:600;margin-bottom:4px">目录 ({{ detailToc.length }} 章)</div>
          <div style="max-height:280px;overflow-y:auto;font-size:12px;border:1px solid #334155;border-radius:6px">
            <div v-for="(ch,j) in detailToc" :key="j" style="padding:4px 8px;border-bottom:1px solid #1e293b">
              {{ j+1 }}. {{ ch.title || '?' }}
            </div>
          </div>
        </div>
        <div class="mt-2 flex gap-2">
          <button class="btn btn-sm btn-success" @click="downloadOne(detailBook)" :disabled="downloading">
            {{ downloading ? '下载中...' : '下载 EPUB' }}
          </button>
          <button class="btn btn-sm btn-outline" @click="detailBook=null">关闭</button>
        </div>
      </div>
    </div>
  </template>

  <!-- ═══ 书源管理 ═══ -->
  <template v-if="tab==='sources'">
    <!-- 统计 -->
    <div class="card">
      <div class="flex items-center justify-between">
        <span>共 <strong>{{ sources.length }}</strong> 个书源</span>
        <div class="flex gap-2">
          <button class="btn btn-sm btn-outline" @click="refreshSources">刷新</button>
          <button class="btn btn-sm btn-primary" @click="exportSources">导出 JSON</button>
        </div>
      </div>
    </div>

    <!-- 添加书源 -->
    <div class="card">
      <details>
        <summary>+ 添加书源（手动）</summary>
        <div class="row mt-2">
          <div style="flex:2">
            <label>名称</label>
            <input v-model="addForm.name" placeholder="如：得奇小说">
          </div>
          <div style="flex:2">
            <label>网址</label>
            <input v-model="addForm.url" placeholder="https://www.example.com">
          </div>
          <div style="flex:1">
            <label>分组（可选）</label>
            <input v-model="addForm.group" placeholder="小说">
          </div>
          <div style="flex:none">
            <label>&nbsp;</label>
            <button class="btn btn-sm btn-success" @click="addSource" :disabled="!addForm.name">添加</button>
          </div>
        </div>
        <details class="mt-2">
          <summary class="text-sm">高级 — 编辑完整规则</summary>
          <div class="mt-2">
            <label>书源 JSON</label>
            <textarea v-model="addForm.json" rows="6" placeholder='{"bookSourceName":"...","bookSourceUrl":"...","ruleSearch":{...}}'></textarea>
          </div>
        </details>
      </details>
    </div>

    <!-- 导入 -->
    <div class="card">
      <details>
        <summary>📥 导入书源</summary>
        <div class="mt-2">
          <label>从 URL 导入（支持 shuyuan 接口）</label>
          <div class="row">
            <input v-model="importUrl" placeholder="https://example.com/sources.json">
            <button class="btn btn-sm btn-primary" @click="importFromUrl" :disabled="!importUrl||importing" style="flex:none">
              <span v-if="importing" class="spinner"></span>导入
            </button>
          </div>
        </div>
        <div class="mt-2">
          <label>上传 JSON 文件</label>
          <div class="import-zone" @click="$refs.jsonInput.click()" @dragover.prevent="isDragOver=true" @dragleave="isDragOver=false" @drop.prevent="handleJsonDrop" :class="{dragover:isDragOver}">
            <div v-if="!jsonFileName">点击或拖拽 .json 文件到此处</div>
            <div v-else>{{ jsonFileName }}</div>
          </div>
          <input ref="jsonInput" type="file" accept=".json" @change="handleJsonFile" style="display:none">
        </div>
        <div class="mt-2">
          <label>上传 ZIP 压缩包（内含 .json 书源）</label>
          <div class="import-zone" @click="$refs.zipInput.click()">
            <div v-if="!zipFileName">点击选择 .zip 文件</div>
            <div v-else>{{ zipFileName }}</div>
          </div>
          <input ref="zipInput" type="file" accept=".zip,.rar" @change="handleZipFile" style="display:none">
        </div>
      </details>
    </div>

    <!-- 书源列表 -->
    <div class="card" style="padding:0;overflow:hidden">
      <table>
        <thead><tr>
          <th style="width:40px">#</th><th>名称</th><th>网址</th><th>分组</th><th style="width:80px">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="s in sources" :key="s.index">
            <td>{{ s.index }}</td>
            <td>
              <a href="#" @click.prevent="editSource(s)" style="color:#38bdf8;text-decoration:none">{{ s.name }}</a>
            </td>
            <td class="mono">{{ s.url }}</td>
            <td><span v-if="s.group" class="badge">{{ s.group }}</span></td>
            <td>
              <button class="btn btn-sm btn-danger" @click="deleteSource(s.index)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 编辑弹窗 -->
    <div v-if="editSourceData" class="modal-overlay" @click.self="editSourceData=null">
      <div class="modal">
        <button class="modal-close" @click="editSourceData=null">&times;</button>
        <h2>编辑书源</h2>
        <div class="text-sm mb-2">{{ editSourceData.name }}</div>
        <label>完整规则 JSON</label>
        <textarea v-model="editSourceJson" rows="20" class="code-block" style="min-height:300px"></textarea>
        <div class="mt-2 flex gap-2">
          <button class="btn btn-sm btn-success" @click="saveEdit">保存</button>
          <button class="btn btn-sm btn-outline" @click="editSourceData=null">取消</button>
        </div>
      </div>
    </div>
  </template>

  <!-- ═══ 关于 ═══ -->
    <template v-if="tab==='about'">
    <div class="card">
      <p><strong>MyBooks Book Source</strong> — 独立版 v1.2</p>
      <p class="text-sm mt-2">书源规则引擎兼容 Legado 3.0。<br>支持 CSS / JSONPath / XPath / JS 规则。<br>EPUB 基于 ebooklib 生成。<br>异步搜索 + 实时进度轮询。</p>
      <p class="text-sm mt-2">书源文件: <code>{{ sourcePath }}</code></p>
    </div>
  </template>
</div>

<script>
const { createApp, ref, computed, onMounted } = Vue;
createApp({
  setup() {
    const tab = ref('search');
    const keyword = ref('');
    const searchSourceIndex = ref(-1);
    const sources = ref([]);
    const results = ref([]);
    const searching = ref(false);
    const searched = ref(false);
    const searchProgress = ref('');
    const downloading = ref(false);
    const downloadStatus = ref('');
    const downloadResult = ref(null);
    const detailBook = ref(null);
    const detailCover = ref('');
    const detailIntro = ref('');
    const detailToc = ref([]);
    const detailWordCount = ref('');

    // source management
    const addForm = ref({ name: '', url: '', group: '', json: '' });
    const importUrl = ref('');
    const importing = ref(false);
    const isDragOver = ref(false);
    const jsonFileName = ref('');
    const jsonFileData = ref(null);
    const zipFileName = ref('');
    const zipFileData = ref(null);
    const editSourceData = ref(null);
    const editSourceJson = ref('');
    const sourcePath = ref('sources.json');

    // toast
    const toast = ref({ show: false, msg: '', type: 'success' });
    let toastTimer = null;
    function showToast(msg, type='success') {
      toast.value = { show: true, msg, type };
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toast.value.show = false; }, 3000);
    }

    async function api(method, path, body) {
      const opts = { method, headers: {} };
      if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
      const r = await fetch(path, opts);
      if (!r.ok) {
        const err = await r.json().catch(()=>({error:r.statusText}));
        throw new Error(err.error || r.statusText);
      }
      return r.json();
    }

    async function loadSources() {
      try {
        sources.value = await api('GET', '/api/sources');
      } catch(e) { showToast('加载书源失败: '+e.message, 'error'); }
    }

    async function doSearch() {
      if (!keyword.value) return;
      searching.value = true;
      searched.value = true;
      results.value = [];
      searchProgress.value = '';
      downloadResult.value = null;
      try {
        const idx = parseInt(searchSourceIndex.value);
        if (idx >= 0) {
          // 单书源 — 同步查询
          results.value = await api('POST', '/api/search', {
            keyword: keyword.value, source_index: idx,
          });
        } else {
          // 全书源 — 创建异步会话 + 轮询
          const { session_id } = await api('POST', '/api/search/start', {
            keyword: keyword.value,
          });
          while (true) {
            await new Promise(r => setTimeout(r, 600));
            const p = await api('GET', '/api/search/progress/' + session_id);
            if (p.results) results.value = p.results;
            searchProgress.value = p.completed + '/' + p.total;
            if (p.status === 'done' || p.status === 'not_found') break;
          }
        }
      } catch(e) { showToast('搜索失败: '+e.message, 'error'); }
      finally { searching.value = false; searchProgress.value = ''; }
    }

    async function showDetail(book) {
      detailBook.value = book;
      detailCover.value = '';
      detailIntro.value = '';
      detailToc.value = [];
      detailWordCount.value = '';
      try {
        const [info, toc] = await Promise.all([
          api('GET', '/api/info?url='+encodeURIComponent(book.bookUrl||'')+'&source_index='+book.sourceIndex),
          api('GET', '/api/toc?url='+encodeURIComponent(book.bookUrl||'')+'&source_index='+book.sourceIndex),
        ]);
        if (info.coverUrl) detailCover.value = info.coverUrl;
        detailIntro.value = info.intro || '';
        detailWordCount.value = info.wordCount || '';
        if (Array.isArray(toc)) detailToc.value = toc;
      } catch(e) {}
    }

    async function download(book) {
      downloading.value = true;
      downloadResult.value = null;
      downloadStatus.value = book.name||'...';
      try {
        const r = await api('POST', '/api/download', {
          bookUrl: book.bookUrl||'',
          keyword: book.name||'未知',
          source_index: book.sourceIndex||0,
          max_chapters: 9999,
        });
        downloadResult.value = r;
        showToast('EPUB 已生成: '+r.path.split('\\').pop());
      } catch(e) { showToast('下载失败: '+e.message, 'error'); }
      finally { downloading.value = false; downloadStatus.value = ''; }
    }

    async function downloadOne(book) { await download(book); }

    async function downloadAll() {
      for (const b of results.value) {
        await download(b);
      }
    }

    // ── source management ──

    async function addSource() {
      let data;
      if (addForm.value.json.trim()) {
        try { data = JSON.parse(addForm.value.json); }
        catch(e) { showToast('JSON 格式错误: '+e.message, 'error'); return; }
      } else {
        data = { bookSourceName: addForm.value.name, bookSourceUrl: addForm.value.url, bookSourceGroup: addForm.value.group };
      }
      try {
        const r = await api('POST', '/api/sources/add', data);
        showToast('已添加: '+r.name);
        addForm.value = { name:'', url:'', group:'', json:'' };
        await loadSources();
      } catch(e) { showToast('添加失败: '+e.message, 'error'); }
    }

    async function deleteSource(index) {
      if (!confirm('确定删除书源 #'+index+'？')) return;
      try {
        const r = await api('POST', '/api/sources/delete', { index });
        showToast('已删除: '+r.name);
        await loadSources();
      } catch(e) { showToast('删除失败: '+e.message, 'error'); }
    }

    function editSource(s) {
      editSourceData.value = s;
      // fetch full detail
      api('GET', '/api/sources/'+s.index).then(d => {
        editSourceJson.value = JSON.stringify(d, null, 2);
      }).catch(e => { showToast('获取详情失败: '+e.message, 'error'); });
    }

    async function saveEdit() {
      try {
        const data = JSON.parse(editSourceJson.value);
        data.index = editSourceData.value.index;
        const r = await api('POST', '/api/sources/update', data);
        showToast('已更新: '+r.name);
        editSourceData.value = null;
        await loadSources();
      } catch(e) { showToast('保存失败: '+e.message, 'error'); }
    }

    async function exportSources() {
      try {
        const data = await api('GET', '/api/sources/export');
        const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'sources_export.json';
        a.click();
        URL.revokeObjectURL(a.href);
        showToast('已导出 '+data.length+' 个书源');
      } catch(e) { showToast('导出失败: '+e.message, 'error'); }
    }

    async function importFromUrl() {
      if (!importUrl.value) return;
      importing.value = true;
      try {
        const r = await api('POST', '/api/import/url', { url: importUrl.value });
        showToast('导入成功: '+r.added+' 个新书源（共 '+r.total+' 个）');
        importUrl.value = '';
        await loadSources();
      } catch(e) { showToast('导入失败: '+e.message, 'error'); }
      finally { importing.value = false; }
    }

    function handleJsonFile(e) {
      const file = e.target.files[0];
      if (!file) return;
      jsonFileName.value = file.name;
      const reader = new FileReader();
      reader.onload = async (ev) => {
        try {
          const r = await api('POST', '/api/import/json', { content: ev.target.result });
          showToast('导入成功: '+r.added+' 个新书源（共 '+r.total+' 个）');
          await loadSources();
        } catch(e) { showToast('导入失败: '+e.message, 'error'); }
      };
      reader.readAsText(file);
    }

    function handleJsonDrop(e) {
      isDragOver.value = false;
      const file = e.dataTransfer.files[0];
      if (!file || !file.name.endsWith('.json')) {
        showToast('请拖入 .json 文件', 'error');
        return;
      }
      jsonFileName.value = file.name;
      const reader = new FileReader();
      reader.onload = async (ev) => {
        try {
          const r = await api('POST', '/api/import/json', { content: ev.target.result });
          showToast('导入成功: '+r.added+' 个新书源（共 '+r.total+' 个）');
          await loadSources();
        } catch(e) { showToast('导入失败: '+e.message, 'error'); }
      };
      reader.readAsText(file);
    }

    function handleZipFile(e) {
      const file = e.target.files[0];
      if (!file) return;
      zipFileName.value = file.name;
      const reader = new FileReader();
      reader.onload = async (ev) => {
        const b64 = ev.target.result.split(',')[1] || ev.target.result;
        try {
          const r = await api('POST', '/api/import/zip', { file: b64 });
          showToast('导入成功: '+r.added+' 个新书源（共 '+r.total+' 个）');
          await loadSources();
        } catch(e) { showToast('导入失败: '+e.message, 'error'); }
      };
      reader.readAsDataURL(file);
    }

    async function refreshSources() { await loadSources(); }

    onMounted(loadSources);

    return {
      tab, keyword, searchSourceIndex, sources, results,
      searching, searched, searchProgress, downloading, downloadStatus, downloadResult,
      detailBook, detailCover, detailIntro, detailToc, detailWordCount,
      addForm, importUrl, importing, isDragOver, jsonFileName, jsonFileData, zipFileName, zipFileData,
      editSourceData, editSourceJson, sourcePath, toast,
      loadSources, doSearch, showDetail, downloadOne, downloadAll,
      addSource, deleteSource, editSource, saveEdit, exportSources,
      importFromUrl, handleJsonFile, handleJsonDrop, handleZipFile, refreshSources,
    };
  }
}).mount('#app');
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
