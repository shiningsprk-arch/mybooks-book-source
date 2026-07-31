# -*- coding: utf-8 -*-
"""本地 HTTP 服务：书源管理 + 多源搜索 + EPUB 生成（独立桌面版，无 MyBooks 依赖）。

API（全部 JSON）:
    GET  /api/sources                         书源列表
    POST /api/sources/save    {raw}           新增/更新书源
    POST /api/sources/delete  {name}          删除书源
    POST /api/sources/toggle  {name,enabled}  启用/停用书源
    POST /api/sources/import_url {url}        从订阅 URL 批量导入
    POST /api/sources/import_zip {file_b64,filename}  从 ZIP 批量导入（优先 importBookSource.json/txt，
                                                      否则扫描包内所有 .json/.txt 逐个解析）
    GET  /api/sources/test?source=           同步搜索 "测试" 验证连通
    POST /api/search          {keyword}       异步多源搜索 -> task_id
    GET  /api/search/status?task_id=          搜索任务进度
    POST /api/epub/generate   {source,bookUrl,bookTitle,maxChapters}
    GET  /api/epub/status?task_id=            生成任务进度
    GET  /api/epub/download?task_id=          下载生成的 EPUB
    POST /api/tasks/cancel    {task_id}       取消生成任务
    GET  /api/explore/categories?source=      分类列表
    GET  /api/explore?source=&url=            分类书籍列表
    GET  /api/config                          读取配置（EPUB 输出目录）
    POST /api/config         {epub_dir}       设置 EPUB 输出目录（空串恢复默认）
    POST /api/config/open                     在文件管理器中打开 EPUB 输出目录
    POST /api/config/pick                     弹出系统文件夹选择对话框，返回选中路径
"""
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from book_source_model import BookSource, load_sources_from_json, dump_sources_to_json
from rule_engine import (search_books, fetch_book_info, fetch_toc, fetch_content,
                         parse_explore_categories, fetch_explore)
from epub_helper import generate_epub as _generate_epub
from search_task_service import SearchTaskService

logger = logging.getLogger("desktop-server")

DATA_DIR = Path(os.environ.get("MYBOOKS_BS_DATA", str(Path.home() / ".mybooks_book_source")))
SOURCES_PATH = DATA_DIR / "sources.json"
CONFIG_PATH = DATA_DIR / "config.json"
BOOKS_DIR = DATA_DIR / "books"
MAX_CHAPTERS = 9999

_WEB_DIR = ""

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


def set_web_dir(path: str):
    global _WEB_DIR
    _WEB_DIR = path


# ── 应用配置（EPUB 输出目录等） ──────────────────────────────────

_config_lock = threading.RLock()


def load_config() -> dict:
    """读取 config.json，缺失或损坏时返回空 dict。"""
    with _config_lock:
        if not CONFIG_PATH.exists():
            return {}
        try:
            return json.loads(CONFIG_PATH.read_text("utf-8"))
        except Exception as exc:
            logger.error("加载配置失败: %s", exc)
            return {}


def save_config(cfg: dict):
    """原子写入 config.json。"""
    with _config_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = str(CONFIG_PATH) + ".tmp"
        Path(tmp).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, str(CONFIG_PATH))


def get_books_dir() -> Path:
    """EPUB 输出目录：优先用户配置，否则默认 DATA_DIR/books。"""
    epub_dir = (load_config().get("epub_dir") or "").strip()
    if epub_dir:
        p = Path(epub_dir).expanduser()
        try:
            p = p.resolve()
        except Exception:
            pass
        return p
    return BOOKS_DIR


# ── 书源持久化 ──────────────────────────────────────────────────

_sources_lock = threading.RLock()


def _seed_sources():
    """首次运行用示例书源填充。"""
    if getattr(sys, "frozen", False):
        seed = Path(sys._MEIPASS) / "sources.json"
    else:
        seed = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "standalone_build", "sources.json"))
    if seed.exists():
        dump_sources_to_json(load_sources_from_json(str(seed)), str(SOURCES_PATH))


def load_sources() -> list[BookSource]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SOURCES_PATH.exists():
        _seed_sources()
    if not SOURCES_PATH.exists():
        return []
    try:
        return load_sources_from_json(str(SOURCES_PATH))
    except Exception as exc:
        logger.error("加载书源失败: %s", exc)
        return []


def save_sources(sources: list[BookSource]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = str(SOURCES_PATH) + ".tmp"
    dump_sources_to_json(sources, tmp)
    os.replace(tmp, str(SOURCES_PATH))


def find_source(name: str) -> BookSource:
    for s in load_sources():
        if s.bookSourceName == name:
            return s
    return None


# ── EPUB 生成任务管理 ───────────────────────────────────────────

class EpubTask:
    def __init__(self, task_id, source, book_url, book_title, max_chapters):
        self.task_id = task_id
        self.source = source
        self.book_url = book_url
        self.book_title = book_title
        self.max_chapters = max_chapters
        self.status = "running"   # running / done / failed / cancelled
        self.progress = 0
        self.message = "初始化"
        self.path = ""
        self.error = ""
        self._cancel = False


class EpubTaskManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._tasks = {}
        self._lock = threading.Lock()

    def start(self, source, book_url, book_title="", max_chapters=MAX_CHAPTERS) -> str:
        task_id = uuid.uuid4().hex[:12]
        task = EpubTask(task_id, source, book_url, book_title, max_chapters)
        with self._lock:
            self._tasks[task_id] = task
        threading.Thread(target=self._run, args=(task,), daemon=True).start()
        return task_id

    def _run(self, task: EpubTask):
        try:
            task.message = "获取书籍信息…"
            detail = fetch_book_info(task.source, task.book_url)
            title = task.book_title or detail.get("name") or "未知书籍"
            author = detail.get("author") or "未知作者"
            cover = detail.get("coverUrl", "")

            task.message = "获取目录…"
            task.progress = 10
            toc = fetch_toc(task.source, task.book_url)
            to_download = [e for e in toc if not e.get("isVolume")][:task.max_chapters]
            total = len(to_download)

            chapters = []
            for i, entry in enumerate(to_download, 1):
                if task._cancel:
                    task.status = "cancelled"
                    task.message = "已取消"
                    return
                ch_title = entry.get("chapterName") or f"第{i}章"
                ch_url = entry.get("chapterUrl", "")
                task.progress = 10 + int(70 * i / max(total, 1))
                task.message = f"下载章节 [{i}/{total}] {ch_title}"
                content = fetch_content(task.source, ch_url)
                if content:
                    chapters.append({"title": ch_title, "content": content, "url": ch_url})

            if not chapters:
                raise ValueError("未获取到有效章节内容（可能书源规则不匹配或站点反爬）")

            task.message = "生成 EPUB…"
            task.progress = 90
            books_dir = get_books_dir()
            books_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", title)
            out_path = books_dir / f"{safe_name}_{task.task_id}.epub"
            _generate_epub(
                title=title, author=author, chapters=chapters,
                cover_url=cover, output_path=str(out_path),
                referer=task.source.bookSourceUrl,
            )
            task.path = str(out_path)
            task.progress = 100
            task.message = "生成完成"
            task.status = "done"
        except Exception as exc:
            logger.exception("生成 EPUB 失败")
            task.status = "failed"
            task.error = str(exc)
            task.message = f"失败：{exc}"

    def status(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task.task_id,
                "status": task.status,
                "progress": task.progress,
                "message": task.message,
                "error": task.error,
                "path": task.path,
                "has_file": bool(task.path and os.path.exists(task.path)),
            }

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != "running":
                return False
            task._cancel = True
            return True


EPUB_TASKS = EpubTaskManager()


# ── HTTP 处理 ───────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "MyBooksBookSource/1.0"

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)

    # ── 工具 ──

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: str):
        with open(path, "rb") as f:
            data = f.read()
        fname = os.path.basename(path)
        ascii_name = fname.encode("ascii", "ignore").decode("ascii").strip() or "download.epub"
        quoted = urllib.parse.quote(fname, safe="")
        self.send_response(200)
        self.send_header("Content-Type", "application/epub+zip")
        # 中文文件名经 latin-1 头编码会 500，必须给 ASCII 兜底 + RFC 5987 filename*
        self.send_header("Content-Disposition",
                         f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _query(self):
        return dict(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))

    def _q1(self, key, default=""):
        vals = self._query().get(key)
        return vals[0] if vals else default

    def _ok(self, data=None, msg="ok"):
        return self._send_json({"err": "ok", "msg": msg, "data": data})

    def _err(self, msg, code=400):
        return self._send_json({"err": "error", "msg": msg}, code)

    # ── 静态页 ──

    def _send_index(self):
        idx = Path(_WEB_DIR) / "index.html"
        if not idx.exists():
            return self._err("web/index.html 缺失（打包或路径问题）", 500)
        data = idx.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── GET ──

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._send_index()
            if path == "/api/sources":
                return self._ok([s.to_dict() for s in load_sources()])
            if path == "/api/config":
                return self._config_get()
            if path == "/api/sources/test":
                return self._test_source()
            if path == "/api/search/status":
                return self._search_status()
            if path == "/api/epub/status":
                return self._epub_status()
            if path == "/api/epub/download":
                return self._epub_download()
            if path == "/api/explore/categories":
                return self._explore_categories()
            if path == "/api/explore":
                return self._explore()
            return self._err("未找到接口: " + path, 404)
        except Exception as exc:
            logger.exception("GET %s 处理失败", self.path)
            return self._send_json({"err": "internal", "msg": str(exc)}, 500)

    # ── POST ──

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self._read_json()
            if path == "/api/sources/save":
                return self._save_source(data)
            if path == "/api/sources/delete":
                return self._delete_source(data)
            if path == "/api/sources/toggle":
                return self._toggle_source(data)
            if path == "/api/sources/import_url":
                return self._import_url(data)
            if path == "/api/sources/import_zip":
                return self._import_zip(data)
            if path == "/api/config":
                return self._config_set(data)
            if path == "/api/config/open":
                return self._config_open()
            if path == "/api/config/pick":
                return self._config_pick()
            if path == "/api/search":
                return self._search(data)
            if path == "/api/epub/generate":
                return self._epub_generate(data)
            if path == "/api/tasks/cancel":
                return self._cancel_task(data)
            return self._err("未找到接口: " + path, 404)
        except Exception as exc:
            logger.exception("POST %s 处理失败", self.path)
            return self._send_json({"err": "internal", "msg": str(exc)}, 500)

    # ── 各接口实现 ──

    def _test_source(self):
        source = find_source(self._q1("source"))
        if not source:
            return self._err("书源不存在")
        results = search_books(source, "测试")
        return self._ok({"source": source.bookSourceName,
                         "count": len(results),
                         "samples": results[:3]})

    def _config_get(self):
        return self._ok({"data_dir": str(DATA_DIR),
                         "epub_dir": str(get_books_dir()),
                         "is_custom": bool(load_config().get("epub_dir"))})

    def _config_set(self, data):
        epub_dir = (data.get("epub_dir") or "").strip()
        if not epub_dir:
            save_config({})
            return self._ok({"epub_dir": str(get_books_dir()),
                             "is_custom": False}, "已恢复默认输出目录")
        p = Path(epub_dir).expanduser()
        try:
            p = p.resolve()
            p.mkdir(parents=True, exist_ok=True)
            # 写测试验证可写
            probe = p / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as exc:
            return self._err(f"目录不可用：{exc}")
        save_config({"epub_dir": str(p)})
        return self._ok({"epub_dir": str(get_books_dir()),
                         "is_custom": True}, "已保存 EPUB 输出目录")

    def _config_open(self):
        books_dir = get_books_dir()
        try:
            books_dir.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(books_dir))
            else:  # pragma: no cover - 桌面版面向 Windows
                import subprocess
                subprocess.Popen(["xdg-open", str(books_dir)])
            return self._ok({"epub_dir": str(books_dir)})
        except Exception as exc:
            return self._err(f"打开目录失败：{exc}")

    def _config_pick(self):
        """弹原生文件夹选择对话框，返回选中路径（取消返回 cancelled）。"""
        import subprocess
        script = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$d.Description = '\u9009\u62e9 EPUB \u8f93\u51fa\u76ee\u5f55';"
            "$d.ShowNewFolderButton = $true;"
            "if ($args[0]) { $d.SelectedPath = $args[0] };"
            "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
            " { Write-Output $d.SelectedPath }"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", script,
                 str(get_books_dir())],
                capture_output=True, timeout=180)
        except Exception as exc:
            return self._err(f"选择目录失败：{exc}")
        path = proc.stdout.decode("utf-8", "replace").strip()
        if not path:
            return self._ok({"path": None, "cancelled": True}, "已取消选择")
        return self._ok({"path": path, "cancelled": False})

    def _search_status(self):
        task_id = self._q1("task_id")
        if not task_id:
            return self._err("缺少 task_id")
        st = SearchTaskService().get_status(task_id)
        if st is None:
            return self._err("任务不存在或已过期", 404)
        return self._ok(st)

    def _epub_status(self):
        task_id = self._q1("task_id")
        if not task_id:
            return self._err("缺少 task_id")
        st = EPUB_TASKS.status(task_id)
        if st is None:
            return self._err("任务不存在", 404)
        return self._ok(st)

    def _epub_download(self):
        task_id = self._q1("task_id")
        st = EPUB_TASKS.status(task_id) if task_id else None
        if not st or st["status"] != "done" or not st["has_file"]:
            return self._err("文件尚未生成")
        return self._send_file(st["path"])

    def _explore_categories(self):
        source = find_source(self._q1("source"))
        if not source:
            return self._err("书源不存在")
        return self._ok(parse_explore_categories(source.exploreUrl))

    def _explore(self):
        source = find_source(self._q1("source"))
        if not source:
            return self._err("书源不存在")
        url = self._q1("url")
        if not url:
            return self._err("缺少 url")
        return self._ok(fetch_explore(source, url))

    def _save_source(self, data):
        raw = data.get("raw")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            return self._err("缺少书源数据")
        if not raw.get("bookSourceName") or not raw.get("bookSourceUrl"):
            return self._err("缺少 bookSourceName 或 bookSourceUrl")
        with _sources_lock:
            sources = load_sources()
            new_source = BookSource.from_dict(raw)
            for i, s in enumerate(sources):
                if s.bookSourceName == new_source.bookSourceName:
                    sources[i] = new_source
                    save_sources(sources)
                    return self._ok({"status": "updated", "name": new_source.bookSourceName})
            sources.append(new_source)
            save_sources(sources)
            return self._ok({"status": "added", "name": new_source.bookSourceName})

    def _delete_source(self, data):
        name = (data.get("name") or "").strip()
        if not name:
            return self._err("缺少 name")
        with _sources_lock:
            sources = load_sources()
            before = len(sources)
            sources = [s for s in sources if s.bookSourceName != name]
            if len(sources) == before:
                return self._err("书源不存在")
            save_sources(sources)
            return self._ok({"status": "deleted", "name": name})

    def _toggle_source(self, data):
        name = (data.get("name") or "").strip()
        if not name:
            return self._err("缺少 name")
        with _sources_lock:
            sources = load_sources()
            for s in sources:
                if s.bookSourceName == name:
                    if data.get("enabled") is not None:
                        s.enabled = bool(data["enabled"])
                    else:
                        s.enabled = not s.enabled
                    save_sources(sources)
                    return self._ok({"status": "toggled", "name": name, "enabled": s.enabled})
            return self._err("书源不存在")

    @staticmethod
    def _merge_items(items) -> tuple:
        """合并书源列表，返回 (added, updated, skipped)。"""
        added = updated = skipped = 0
        with _sources_lock:
            sources = load_sources()
            for item in items:
                if not isinstance(item, dict) or not item.get("bookSourceName"):
                    skipped += 1
                    continue
                src = BookSource.from_dict(item)
                for i, s in enumerate(sources):
                    if s.bookSourceName == src.bookSourceName:
                        sources[i] = src
                        updated += 1
                        break
                else:
                    sources.append(src)
                    added += 1
            save_sources(sources)
        return added, updated, skipped

    def _import_url(self, data):
        url = (data.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self._err("URL 必须是 http/https")
        try:
            resp = requests.get(url, timeout=30,
                                headers={"User-Agent": _UA, "Accept": "application/json"})
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return self._err(f"拉取失败：{exc}")
        items = payload if isinstance(payload, list) else [payload]
        added, updated, skipped = self._merge_items(items)
        return self._ok({"added": added, "updated": updated, "skipped": skipped},
                        f"导入完成：新增 {added}，更新 {updated}，跳过 {skipped}")

    def _import_zip(self, data):
        """从 ZIP 压缩包导入书源。

        优先解析 Legado 标准导出（importBookSource.json/txt）；
        找不到时兜底扫描包内所有 .json/.txt 文件逐个解析（每文件一个书源或数组）。
        """
        import base64 as _b64
        import io as _io
        import zipfile as _zf
        b64 = (data.get("file_b64") or "").strip()
        if not b64:
            return self._err("缺少文件数据")
        try:
            raw = _b64.b64decode(b64)
        except Exception as exc:
            return self._err(f"文件解码失败：{exc}")
        if len(raw) > 10 * 1024 * 1024:
            return self._err("压缩包超过 10MB")
        try:
            with _zf.ZipFile(_io.BytesIO(raw)) as zf:
                names = zf.namelist()

                def _base(name):
                    return name.replace("\\", "/").rsplit("/", 1)[-1]

                # 1) Legado 标准导出
                target = next((n for n in names
                               if _base(n) in ("importBookSource.json", "importBookSource.txt")), None)
                if target is not None:
                    text = zf.read(target).decode("utf-8", errors="replace")
                    try:
                        payload = json.loads(text)
                    except Exception as exc:
                        return self._err(f"书源文件 {target} JSON 解析失败：{exc}")
                    items = payload if isinstance(payload, list) else [payload]
                    source_files = [target]
                else:
                    # 2) 兜底：遍历所有 json/txt 文件
                    items = []
                    source_files = []
                    for name in names:
                        base = _base(name)
                        if not (base.endswith(".json") or base.endswith(".txt")):
                            continue
                        try:
                            payload = json.loads(zf.read(name).decode("utf-8", errors="replace"))
                        except Exception:
                            continue
                        if isinstance(payload, list):
                            items.extend(payload)
                            source_files.append(name)
                        elif isinstance(payload, dict):
                            items.append(payload)
                            source_files.append(name)
                    if not source_files:
                        return self._err("压缩包内未找到可解析的书源文件（.json/.txt）")
        except Exception as exc:
            return self._err(f"压缩包解析失败：{exc}")
        added, updated, skipped = self._merge_items(items)
        detail = f"（解析 {len(source_files)} 个文件）" if len(source_files) > 1 else ""
        return self._ok({"added": added, "updated": updated, "skipped": skipped,
                         "files": len(source_files)},
                        f"导入完成：新增 {added}，更新 {updated}，跳过 {skipped}{detail}")

    def _search(self, data):
        keyword = (data.get("keyword") or "").strip()
        if not keyword:
            return self._err("缺少 keyword")
        source_names = data.get("source_names")
        sources = load_sources()
        targets = sources if source_names is None else [
            s for s in sources if s.bookSourceName in source_names]
        targets = [s for s in targets if s.enabled]
        if not targets:
            return self._err("没有已启用的书源")
        items = [{"name": s.bookSourceName, "source": s} for s in targets]
        result = SearchTaskService().create_task(keyword, items)
        return self._ok(result)

    def _epub_generate(self, data):
        source = find_source((data.get("source") or "").strip())
        if not source:
            return self._err("书源不存在")
        book_url = (data.get("bookUrl") or "").strip()
        if not book_url:
            return self._err("缺少 bookUrl")
        try:
            max_chapters = int(data.get("maxChapters", MAX_CHAPTERS))
        except (TypeError, ValueError):
            max_chapters = MAX_CHAPTERS
        max_chapters = max(1, min(max_chapters, MAX_CHAPTERS))
        task_id = EPUB_TASKS.start(source, book_url,
                                   (data.get("bookTitle") or "").strip(), max_chapters)
        return self._ok({"task_id": task_id})

    def _cancel_task(self, data):
        task_id = (data.get("task_id") or "").strip()
        if not task_id:
            return self._err("缺少 task_id")
        if EPUB_TASKS.cancel(task_id):
            return self._ok({"task_id": task_id}, "已请求取消")
        return self._err("任务不存在或已完成")


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv
