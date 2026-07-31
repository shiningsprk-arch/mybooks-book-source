# -*- coding: UTF-8 -*-
"""L2a 集成冒烟：书源引擎插件 × 真实 MyBooks 目标接口。

本脚本在「真实目标源码树」上运行（验证插件与目标接口的兼容性），
不属于插件单元测试（unittest discover 默认排除本目录）。

用法（在本机 L2a 环境或 MyBooks 源码检出根目录）:
    python tools/integration_smoke.py

依赖目标仓库的 webserver 包（含 handlers/base.py、toolbox/base_tool.py、
services/async_service.py 等），本机无需 calibre——所有 calibre 引用均为
函数内懒加载。缺 dukpy 时 JS 相关路径自动降级。

覆盖：
1. 工具层 — 真实 BaseTool/AsyncService/BackgroundService：
   create_task → update_task_progress → complete_task → get_last_task；
   list/add/toggle/delete 书源 CRUD；get_work_dir；get_last_epub_path。
2. Handler 层 — tornado AsyncHTTPTestCase 挂载真实 toolbox.routes()：
   14 条 book_source 路由逐一请求，校验响应结构 {"err": "ok", ...}。
3. ToolSet 注册 — /api/toolbox/list 包含 book_source。
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tornado
from tornado.testing import AsyncHTTPTestCase
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver.handlers.base import BaseHandler
from webserver.handlers.toolbox import routes
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.book_source_tool import BookSourceTool
from webserver.toolbox.toolset import ToolSet

DUMMY_SOURCE = {
    "bookSourceName": "L2A测试源",
    "bookSourceUrl": "https://example.com",
    "enable": True,
    "ruleSearch": {"bookList": "json:books", "name": "name", "bookUrl": "url"},
}


class DummyUser:
    def is_admin(self):
        return True


class DummyLegacy:
    new_api = None


def _app_settings():
    engine = create_engine("sqlite:///:memory:")
    scoped = scoped_session(sessionmaker(bind=engine))
    AsyncService().setup(None, scoped)
    return {
        "cookie_secret": "l2a-test-secret",
        "ScopedSession": scoped,
        "legacy": DummyLegacy(),
        "build_time": 0,
        "default_cover": "",
    }


def _patch_base_handler():
    from webserver.handlers import base as _base

    _base.CONF["installed"] = True
    _base.CONF["invited"] = True

    def fake_get_current_user(self):
        if not self.admin_user:
            self.admin_user = DummyUser()
        return self.admin_user

    BaseHandler.get_current_user = fake_get_current_user
    BaseHandler.user_id = lambda self: 1
    BaseHandler.current_user = property(lambda self: self.get_current_user())
    print("PATCHED: current_user in BaseHandler dict:",
          "current_user" in BaseHandler.__dict__, file=sys.stderr)


class TestToolLayer(unittest.TestCase):
    """工具层：真实 BaseTool 接口链路。"""

    @classmethod
    def setUpClass(cls):
        cls._data_root = tempfile.mkdtemp(prefix="bs_tool_")
        BookSourceTool.TOOL_DATA_ROOT = cls._data_root

    def test_task_lifecycle(self):
        tool = BookSourceTool()
        task_id = tool.create_task(progress_data={"total": 3, "done": 0})
        self.assertIsInstance(task_id, int)
        task = BackgroundService().get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.get("status"), BackgroundTask.STATUS_RUNNING)
        self.assertEqual(task.get("service_item"), "书源管理")
        self.assertEqual(task.get("service_type"), BackgroundTask.SERVICE_TYPE_OTHER)

        tool.update_task_progress(task_id, 50, {"status": "抓取中"})
        task = BackgroundService().get_task(task_id)
        self.assertEqual(task.get("progress"), 50)
        self.assertEqual(task.get("progress_data", {}).get("status"), "抓取中")

        tool.complete_task(task_id)
        task = BackgroundService().get_task(task_id)
        self.assertEqual(task.get("status"), BackgroundTask.STATUS_COMPLETED)

        # get_last_task 经由 classmethod 读取（set_last_task 由下载/生成任务写入）
        BookSourceTool.set_last_task(1, task_id)
        last = BookSourceTool.get_last_task(1)
        self.assertEqual(last.get("id"), task_id)
        self.assertFalse(BookSourceTool.is_running(1))

    def test_task_failure(self):
        tool = BookSourceTool()
        task_id = tool.create_task()
        tool.complete_task(task_id, error_message="超时")
        task = BackgroundService().get_task(task_id)
        self.assertEqual(task.get("status"), BackgroundTask.STATUS_FAILED)
        self.assertEqual(task.get("error_message"), "超时")

    def test_cancel_task(self):
        tool = BookSourceTool()
        task_id = tool.create_task()
        self.assertTrue(BackgroundService().cancel_task(task_id))
        task = BackgroundService().get_task(task_id)
        self.assertEqual(task.get("status"), BackgroundTask.STATUS_CANCELLED)

    def test_source_crud(self):
        tool = BookSourceTool()
        self.assertEqual(tool.list_sources(), [])
        rsp = tool.add_source(DUMMY_SOURCE)
        self.assertEqual(rsp["status"], "added")
        self.assertEqual(len(tool.list_sources()), 1)
        self.assertEqual(tool.get_source("L2A测试源")["bookSourceName"], "L2A测试源")
        rsp = tool.add_source(DUMMY_SOURCE)
        self.assertEqual(rsp["status"], "updated")
        rsp = tool.toggle_source("L2A测试源")
        self.assertIn(rsp["status"], ("ok", "toggled"))
        rsp = tool.delete_source("L2A测试源")
        self.assertIn(rsp["status"], ("ok", "deleted"))
        self.assertEqual(tool.list_sources(), [])
        rsp = tool.delete_source("不存在")
        self.assertEqual(rsp["status"], "not_found")

    def test_work_dir_and_epub_path(self):
        tool = BookSourceTool()
        work_dir = tool.get_work_dir("https://example.com/book/1")
        self.assertTrue(os.path.isdir(work_dir))
        self.assertIn("book_source", work_dir)
        self.assertFalse(tool.get_last_epub_path(1))

    def test_toolset_registration(self):
        ToolSet._tool_set.clear()
        ToolSet.collect_tools()
        tool = ToolSet.get_tool("book_source")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "书源管理")
        self.assertEqual(tool.revision, "1.2.0")
        self.assertEqual(tool.author, "MyBooks")
        d = tool.to_dict()
        for key in ("id", "name", "description", "revision", "author"):
            self.assertIn(key, d)


class TestHandlerLayer(AsyncHTTPTestCase):
    """Handler 层：真实 routes() 挂载 + @js/@is_admin 响应契约。"""

    @classmethod
    def setUpClass(cls):
        cls._data_root = tempfile.mkdtemp(prefix="bs_api_")
        BookSourceTool.TOOL_DATA_ROOT = cls._data_root
        _patch_base_handler()

    def get_app(self):
        return tornado.web.Application(routes(), **_app_settings())

    def test_route_table_completeness(self):
        paths = {r[0] for r in routes()}
        expected = [
            "/api/toolbox/book_source/list",
            "/api/toolbox/book_source/save",
            "/api/toolbox/book_source/toggle",
            "/api/toolbox/book_source/delete",
            "/api/toolbox/book_source/search_async",
            "/api/toolbox/book_source/search_status",
            "/api/toolbox/book_source/test",
            "/api/toolbox/book_source/download",
            "/api/toolbox/book_source/generate_epub",
            "/api/toolbox/book_source/cancel",
            "/api/toolbox/book_source/progress",
            "/api/toolbox/book_source/import_zip",
            "/api/toolbox/book_source/import_url",
            "/api/toolbox/book_source/download_epub",
        ]
        for p in expected:
            self.assertIn(p, paths, f"缺少路由 {p}")

    def test_tool_list_includes_book_source(self):
        rsp = self.fetch("/api/toolbox/list", method="GET")
        self.assertEqual(rsp.code, 200)
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "ok")
        ids = [t["id"] for t in body["tools"]]
        self.assertIn("book_source", ids)

    def _post_json(self, path, payload):
        return self.fetch(path, method="POST", body=json.dumps(payload, ensure_ascii=False),
                          headers={"Content-Type": "application/json"})

    def test_list_and_save(self):
        rsp = self.fetch("/api/toolbox/book_source/list")
        self.assertEqual(rsp.code, 200)
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "ok")
        self.assertIsInstance(body["data"], list)

        rsp = self._post_json("/api/toolbox/book_source/save", {"raw": DUMMY_SOURCE})
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "ok")
        self.assertIn(body["data"]["status"], ("added", "updated"))

        rsp = self._post_json("/api/toolbox/book_source/save", {"raw": {}})
        self.assertNotEqual(json.loads(rsp.body)["err"], "ok")

    def test_toggle_delete(self):
        self._post_json("/api/toolbox/book_source/save", {"raw": DUMMY_SOURCE})
        rsp = self._post_json("/api/toolbox/book_source/toggle", {"name": "L2A测试源"})
        self.assertEqual(json.loads(rsp.body)["err"], "ok")
        rsp = self._post_json("/api/toolbox/book_source/toggle", {"name": "不存在"})
        self.assertEqual(json.loads(rsp.body)["err"], "book_source.not_found")
        rsp = self._post_json("/api/toolbox/book_source/delete", {"name": "L2A测试源"})
        self.assertEqual(json.loads(rsp.body)["err"], "ok")

    def test_test_unknown_source(self):
        rsp = self.fetch("/api/toolbox/book_source/test?source=不存在")
        self.assertEqual(rsp.code, 200)
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "book_source.invalid")

    def test_search_async_and_status(self):
        self._post_json("/api/toolbox/book_source/save", {"raw": DUMMY_SOURCE})
        rsp = self._post_json("/api/toolbox/book_source/search_async", {"keyword": "测试"})
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "ok")
        task_id = body["data"]["task_id"]
        self.assertTrue(task_id)

        deadline = time.time() + 20
        final = None
        while time.time() < deadline:
            rsp = self.fetch(f"/api/toolbox/book_source/search_status?task_id={task_id}")
            body = json.loads(rsp.body)
            self.assertEqual(body["err"], "ok")
            final = body["data"]
            if final.get("done", 0) + final.get("failed", 0) >= final.get("total", 1):
                break
            time.sleep(0.5)
        self.assertIsNotNone(final)
        self.assertIn("results", final)

        rsp = self.fetch("/api/toolbox/book_source/search_status?task_id=999999")
        self.assertEqual(json.loads(rsp.body)["err"], "task.not_found")

    def test_progress_and_cancel(self):
        rsp = self.fetch("/api/toolbox/book_source/progress")
        self.assertEqual(rsp.code, 200)
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "ok")
        self.assertIn("data", body)
        if body["data"] is not None:
            for key in ("task_id", "progress", "status", "progress_data"):
                self.assertIn(key, body["data"])

        rsp = self._post_json("/api/toolbox/book_source/cancel", {"task_id": 999999})
        self.assertEqual(json.loads(rsp.body)["err"], "task.not_found")

    def test_import_zip_missing_file(self):
        rsp = self.fetch("/api/toolbox/book_source/import_zip", method="POST", body=b"")
        self.assertEqual(json.loads(rsp.body)["err"], "params.missing")

    def test_import_url_invalid(self):
        rsp = self._post_json("/api/toolbox/book_source/import_url", {"url": "not-a-url"})
        self.assertEqual(json.loads(rsp.body)["err"], "book_source.import_failed")

    def test_download_epub_404(self):
        rsp = self.fetch("/api/toolbox/book_source/download_epub")
        self.assertEqual(rsp.code, 404)

    def test_download_starts_task(self):
        self._post_json("/api/toolbox/book_source/save", {"raw": DUMMY_SOURCE})
        rsp = self._post_json("/api/toolbox/book_source/download", {
            "source": "L2A测试源",
            "bookUrl": "https://example.com/book/1",
            "bookTitle": "测试书",
            "maxChapters": 3,
        })
        body = json.loads(rsp.body)
        self.assertEqual(body["err"], "ok")
        deadline = time.time() + 10
        last = None
        while time.time() < deadline:
            last = BookSourceTool.get_last_task(1)
            if last is not None:
                break
            time.sleep(0.2)
        self.assertIsNotNone(last)
        self.assertIn(last.get("status"),
                      (BackgroundTask.STATUS_RUNNING, BackgroundTask.STATUS_FAILED))

    def test_generate_epub_starts_task(self):
        self._post_json("/api/toolbox/book_source/save", {"raw": DUMMY_SOURCE})
        rsp = self._post_json("/api/toolbox/book_source/generate_epub", {
            "source": "L2A测试源",
            "bookUrl": "https://example.com/book/1",
            "bookTitle": "测试书",
        })
        self.assertEqual(json.loads(rsp.body)["err"], "ok")
        last = BookSourceTool.get_last_task(1)
        self.assertIsNotNone(last)


if __name__ == "__main__":
    unittest.main(verbosity=2)
