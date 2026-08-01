# Book Source Engine Enhancement — PR Changeset

## Overview

This PR enhances the existing book source engine (`webserver/toolbox/book_source_engine/`) and the corresponding Toolbox tool (`webserver/toolbox/book_source_tool.py`), adding multi-page TOC/content fetching, rule combinators, source validation, async multi-source search, explore/category browsing, and a full Vue management page.

Target branch: `mybooks-3.49.0` (or current main)

---

## File Map — Target: `mybooks源码/mybooks-3.49.0/`

### Files to REPLACE (existing → new version)

| # | Target Path | Lines (Δ) | Key Changes |
|---|------------|-----------|-------------|
| 1 | `webserver/toolbox/book_source_engine/book_source_model.py` | 209→215 (Δ +6) | Add `init` field to `RuleSearch`, `RuleBookInfo`, `RuleToc`, `RuleContent`; add `nextTocUrl` to `RuleToc`; `_content_from_dict` reads `init` |
| 2 | `webserver/toolbox/book_source_engine/rule_engine.py` | 918→1328 (Δ +410) | Add `@css:` prefix, `\|\|`/`&&`/`%%`/`@put:`/`@get:` combinators, `build_source_session()`, multi-page TOC/content via `deque` + `nextTocUrl`/`nextContentUrl`, `parse_explore_categories()`, `fetch_explore()`, `_dedupe_chapters()`, `make_doc()`, variables dict, per-call session |
| 3 | `webserver/toolbox/book_source_engine/__init__.py` | 5→5 (Δ 0) | Add `fetch_explore`, `parse_explore_categories` to exports |
| 4 | `webserver/toolbox/book_source_tool.py` | 324→581 (Δ +257) | Add `validate_source()`, `search_async()`/`get_search_status()`/`search_all()`, `import_sources_from_url()`, `explore_categories()`/`explore()`, `generate_epub()` enhancements, `_iter_rule_values()`, `_has_unsupported_js()`, `_requires_js()`, `_source_tags()`, `_missing_required_features()` |

### Files to ADD (new)

| # | Target Path | Lines | Purpose |
|---|------------|-------|---------|
| 5 | `webserver/toolbox/book_source_engine/search_task_service.py` | 164 | Singleton async multi-source search with `ThreadPoolExecutor`, task TTL cleanup, polling via `get_status(task_id)` |
| 6 | `app/pages/toolbox/book_source.vue` | 783 | Vue 2 + Vuetify 2 management page: two-tab layout (Search + Source Management), download tracking, polling progress, JSON editor, ZIP/URL import, test connectivity |
| 7 | `tests/test_book_source_engine.py` | 890+ | 109 unit tests covering all engine modules (CSS, JSONPath, XPath, Legado, JS, full flow, edge cases) |
| 8 | `tools/generate_epub_from_source.py` | 114 | Standalone CLI: `python generate_epub.py <keyword> [max_chapters]` — search → toc → content → epub |
| 9 | `tests/data/sample_sources.json` | 119 | 3 example book sources (笔趣阁, 得奇小说, 知轩藏书) |
| 10 | `tests/data/deqixs_test.json` | 41 | Test fixture for deqixs.com (POST search, @js: content, jsLib) |

### Files to UPDATE (partial)

| # | Target Path | Action |
|---|------------|--------|
| 11 | `webserver/handlers/toolbox.py` | Add routes: `search_async`, `search_status`, `validate`, `explore_categories`, `explore` (all already present in target's `toolbox.py`, no handler change needed for those 4 — check routes at line 549-610) |
| 12 | `webserver/toolbox/book_source_engine/epub_helper.py` | Minor: workspace uses `book.set_cover()` vs existing `EpubImage` object — functionally identical, recommend keeping existing version |

### Files with NO CHANGE (identical in workspace & target)

- `webserver/toolbox/book_source_engine/js_runtime.py` (111 lines)
- `webserver/toolbox/book_source_engine/content_fallbacks.py` (198 lines)

---

## Key Technical Differences (workspace vs target existing)

### book_source_model.py — Field Additions

```diff
 class RuleSearch:
+    init: str = ""         # initialization JS/variables

 class RuleBookInfo:
+    init: str = ""

 class RuleToc:
+    init: str = ""
+    nextTocUrl: str = ""   # paginated TOC support

 class RuleContent:
+    init: str = ""
```

### rule_engine.py — Major Additions

1. **`@css:` explicit prefix** — `parse_selector` first checks for `@css:` prefix, disambiguating CSS from Legado selectors
2. **Combinators in `extract_single()`**:
   - `||` — first non-empty (try A, fall back to B)
   - `&&` — concatenation (A + B)
   - `@put:key` — store value in shared variables dict
   - `@get:key` — retrieve from variables dict
3. **Combinators in `extract_list()`**:
   - `||` — first non-empty list
   - `%%` — interleave merge
4. **Multi-page TOC (`fetch_toc`)**:
   - Uses `deque` to process pages; extracts `nextTocUrl` from each page; loops until empty
   - `_dedupe_chapters()` eliminates duplicates across pages
5. **Multi-page content (`fetch_content`)**:
   - Processes `nextContentUrl` for long articles split across pages
6. **Explore** (`parse_explore_categories`, `fetch_explore`):
   - Parses `exploreUrl` → category list → `fetch_explore()` extracts book lists
7. **`build_source_session()`** — creates a `requests.Session` pre-configured with source headers & cookies
8. **`make_doc()`** — unified soup factory with XML declaration handling
9. **`variables` dict** — shared mutable dict threaded through all extraction calls for `@put:`/`@get:`

### book_source_tool.py — New Methods

| Method | Description |
|--------|-------------|
| `validate_source(raw: dict)` | DNS resolution → HTTP probe → JS dependency detection → feature completeness check → auto-tag (post/search/toc/content/explore/fulltext) |
| `search_async(keyword, source_names)` | Creates async search task via `SearchTaskService`, returns task_id immediately |
| `get_search_status(task_id)` | Returns progress snapshot (done/total/results/pending/partial) |
| `search_all(keyword, timeout)` | Synchronous convenience: waits for all sources via polling |
| `import_sources_from_url(url)` | Fetches remote JSON (GET), parses & import-sources |
| `explore_categories(source)` | Parses `exploreUrl` for category navigation |
| `explore(source, url)` | Fetches book list from category URL |
| `generate_epub()` (enhanced) | Now accepts all sources, better error handling |

### search_task_service.py — Architecture

Mirrors Talebook's `BookSourceSearchService`:

```
SearchTaskService (singleton)
├── ThreadPoolExecutor (max_workers=10)
├── create_task(keyword, sources) → task_id   # immediately returns
├── get_status(task_id) → snapshot             # polled by caller
├── _run_one(task_id, keyword, source)         # runs in background thread
└── _cleanup()                                 # TTL=300s, expired task removal
```

### Import Adjustment Required

All workspace `.py` files use **absolute direct imports** (`from js_runtime import ...`). Before merging into the target `book_source_engine/` package, they must be changed to **relative imports**:

| File | Change |
|------|--------|
| `rule_engine.py` | `from js_runtime import` → `from .js_runtime import` |
| `search_task_service.py` | `from rule_engine import` → `from .rule_engine import` |
| `test_book_source_engine.py` | `from book_source_model import` → `from webserver.toolbox.book_source_engine import` |
| `generate_epub_from_source.py` (CLI) | Keep absolute (standalone, not part of package) |

---

## Dependencies (add to `requirements.txt`)

```
beautifulsoup4>=4.12
lxml>=5.0
requests>=2.31
dukpy>=0.4.0
ebooklib>=0.18
```

---

## Step-by-Step Integration

```
mybooks-3.49.0/
├── webserver/toolbox/book_source_engine/
│   ├── __init__.py              # REPLACE — add fetch_explore, parse_explore_categories to exports
│   ├── book_source_model.py     # REPLACE — add init/nextTocUrl fields
│   ├── rule_engine.py           # REPLACE — add combinators, multi-page, explore, variables
│   ├── js_runtime.py            # keep existing (identical)
│   ├── content_fallbacks.py     # keep existing (identical)
│   ├── epub_helper.py           # keep existing (minor diff, not breaking)
│   └── search_task_service.py   # ADD — new file (fix imports to relative)
├── webserver/toolbox/book_source_tool.py   # REPLACE
├── app/pages/toolbox/
│   └── book_source.vue          # ADD
├── tests/
│   ├── test_book_source_engine.py  # ADD
│   └── data/
│       ├── sample_sources.json     # ADD
│       └── deqixs_test.json        # ADD
└── tools/
    └── generate_epub_from_source.py  # ADD
```

### Handler Routes (toolbox.py)

The existing `toolbox.py` already has routes for all endpoints — verify they match the new `book_source_tool.py` method signatures:

| Route | Handler | Method |
|-------|---------|--------|
| `/api/toolbox/book_source/list` | `AdminBookSourceList.get` | `list_sources()` |
| `/api/toolbox/book_source/save` | `AdminBookSourceSave.post` | `add_source()` |
| `/api/toolbox/book_source/delete` | `AdminBookSourceDelete.post` | `delete_source()` |
| `/api/toolbox/book_source/toggle` | `AdminBookSourceToggle.post` | `toggle_source()` |
| `/api/toolbox/book_source/search` | `AdminBookSourceSearch.get` | `search()` |
| `/api/toolbox/book_source/test` | `AdminBookSourceTest.get` | `test_source()` |
| `/api/toolbox/book_source/download` | `AdminBookSourceDownload.post` | `download_book()` |
| `/api/toolbox/book_source/progress` | `AdminBookSourceProgress.get` | `get_last_task()` |
| `/api/toolbox/book_source/import_zip` | `AdminBookSourceImportZip.post` | `import_sources_from_zip()` |
| `/api/toolbox/book_source/import_url` | `AdminBookSourceImportUrl.post` | `import_sources_from_url()` |
| `/api/toolbox/book_source/validate` | `AdminBookSourceValidate.post` | `validate_source()` |
| `/api/toolbox/book_source/explore_categories` | `AdminBookSourceExploreCategories.get` | `explore_categories()` |
| `/api/toolbox/book_source/explore` | `AdminBookSourceExplore.get` | `explore()` |

All existing routes remain compatible. No handler code changes needed — only the tool implementation changes.

---

## Verification

```bash
# Unit tests (after import fix)
cd webserver/toolbox/book_source_engine
python -m pytest ../../../../tests/test_book_source_engine.py -v

# Manual test
python -c "
from webserver.toolbox.book_source_tool import BookSourceTool
t = BookSourceTool()
print('list:', len(t.list_sources()))
print('validate:', t.validate_source({'bookSourceName':'test','bookSourceUrl':'https://example.com'}))
"
```

Expected: 109 tests pass, all new methods functional.

---

## Round 2026-07-31 �� Anti-scrape layer + Configurable EPUB output dir

| Area | Change |
| --- | --- |
| rule_engine.py | UA rotation pool (\_UA_POOL\ + \_pick_ua\), browser-style headers (Sec-Fetch-*, Accept-Encoding), jittered throttle (\MYBOOKS_FETCH_JITTER\), status-aware retry (\_do_http\: 429 Retry-After / 403+5xx backoff + UA rotate), proxy support (\MYBOOKS_PROXY\), optional curl_cffi Chrome TLS impersonation (\MYBOOKS_HTTP_BACKEND\), chardet-based decode (\_response_text\), zero-width char cleanup (\
ormalize_content_text\, adapted from talebook cleaner) |
| epub_helper.py | Reuse anti-scrape session via \uild_source_session\; shared \_browser_headers\; \_make_session\ |
| content_fallbacks.py | Reuse \uild_source_session\ in \	ry_fetch_content\ |
| desktop/server.py | \config.json\ persistence, \get_books_dir()\, GET/POST \/api/config\, \/api/config/open\ (open folder in Explorer) |
| desktop/web/index.html | New ���� tab: EPUB ���Ŀ¼ input + save / reset / open |
| README.md | NEW �� project doc + anti-scrape env vars + BSD-2 attribution to talebook |
| test_rule_engine.py | +8 tests (UA pool, session headers, retry on 429, declared encoding, zero-width normalization) �� 117 total |

---

## Round 2026-07-31 (2) — PyInstaller spec fixes + backend logging

| Area | Change |
| --- | --- |
| mybooks-book-source-app.spec | Fix relative paths (build from any CWD): `ROOT = SPECPATH`, absolute `pathex`/`datas`. curl_cffi bundled via `collect_all` (`_wrapper.pyd` as EXTENSION + dist-info). Verified in final EXE TOC. |
| rule_engine.py | `_new_session()` now logs selected backend (`HTTP backend: curl_cffi (Chrome TLS 指纹)` / `requests`) — proves frozen app loads curl_cffi. |
| Build command | `python -m PyInstaller --noconfirm --clean <spec>` — do NOT pass `--onefile/--console/--name` (spec already has them). |

### Packaging verification (frozen exe)
- `/api/config` GET/POST (set custom epub_dir, persist, re-read) OK.
- `/api/sources` returns 3 sources.
- Forced `MYBOOKS_HTTP_BACKEND=curl_cffi`: exe logs `HTTP backend: curl_cffi (Chrome TLS 指纹)` → curl_cffi + TLS impersonation active inside bundled app.
- 117 unit tests still pass (`python -m unittest test_rule_engine.py`).

---

## Round 2026-07-31 (3) — Code review bugfixes

| Area | Change |
| --- | --- |
| epub_helper.py | FIX: `_inline_images` uid/文件名按章节编号（ch0001_img0000.jpg…），多章节含图的书不再互相覆盖/uid 冲突；`_download_cover` 改为返回字节不落盘，EPUB 输出目录不再残留 cover.jpg 垃圾文件 |
| desktop/web/index.html | FIX: 生成完成消息里的下载链接不再被 esc() 转义成纯文本（独立 `t.link` 渲染为可点按钮）；失败任务 chip 用红色 `.chip.bad` 区分 |
| desktop/server.py | FIX: `maxChapters` 非法输入不再 500（默认/夹紧到 1..9999）；`_config_set` 保存前 resolve 路径，相对路径不再依赖运行时 CWD |
| rule_engine.py | FIX: Legado 开区间索引规则（如 `class.list[0:]`）作用在缺失元素上返回 `[]` 而非抛 IndexError 中断整个搜索/目录；`Retry-After` 上限 60s 防异常站点无限等待 |
| test_rule_engine.py | +2 tests：多章节图片无冲突（回归）、Legado 空元素开区间不崩溃 → 119 total |

### 验证
- 119 单测全过；dev 模式 API 冒烟（config 设置/恢复、maxChapters=abc → 200 且按默认值启任务、epub 输出目录 resolve 持久化）。
- 冻结 exe 重建并实测：config / sources / sources/test / curl_cffi backend 全部正常。

## Round 2026-07-31 (4) — 桌面 UI 改版：侧边栏 + 默认搜索页 + 结果排序

| Area | Change |
| --- | --- |
| desktop/web/index.html | 布局改为「左侧边栏 + 主区」：侧边栏含导航（搜索下载 / 书源管理）、EPUB 输出目录设置（保存/恢复默认/打开目录，默认页即可改）、任务进度列表（始终可见）；原「设置」页并入侧边栏删除 |
| desktop/web/index.html | 对调「书源管理」与「搜索下载」顺序，默认打开「搜索下载」 |
| desktop/web/index.html | 搜索结果按相关度排序：书名完全匹配 > 前缀匹配 > 包含匹配 > 作者匹配 > 其余；同级按书名长度短者优先、中文 locale 排序、来源名稳定排序，并随轮询实时重排 |

### 验证
- 119 单测全过；node 语法检查 + 排序逻辑单测（斗破苍穹 → 完全匹配 1000 > 番外 800 > 新斗破 600 > 无关书 200）。
- dev 模式冒烟：config 设置/持久化/恢复正常（PowerShell 中文 body 编码问题为测试脚本自身问题，Python 直连验证通过）。
- 冻结 exe 重建（40.6MB）实测：新 UI markers 全部命中、设置面板已移除、多源搜索流式返回正常。

## Round 2026-07-31 (5) — FIX: 下载 EPUB 报 latin-1 codec 500

| Area | Change |
| --- | --- |
| desktop/server.py | FIX: `_send_file` 的 `Content-Disposition` 直接拼中文文件名（书名），http.server 以 latin-1 编码响应头导致 `'latin-1' codec can't encode...` 整页 500。改为 ASCII 兜底 `filename="…"` + RFC 5987 `filename*=UTF-8''…`（percent 编码），中文名浏览器正常显示 |

### 验证
- 单测直连 `_send_file`（中文文件名 epub）：响应头全部 ASCII 可解码，`Content-Disposition: attachment; filename="__abcd1234.epub"; filename*=UTF-8''%E6%96%97%E7%A0%B4…`，正文完整，latin-1 不再炸。
- 119 单测全过；冻结 exe 重建（40.6MB）页面/配置正常；v0.1.0 Release 资产已替换为修复版。

## Round 2026-07-31 (6) — 系统要求入 README + EPUB 输出目录文件夹选择

| Area | Change |
| --- | --- |
| README.md | 新增「系统要求（Windows 桌面版 exe）」：64 位 Win10/11、免装 Python/VC++ 运行库（已内置）、需联网、免管理员、SmartScreen 首次拦截提示、控制台窗口勿关；修正 EPUB 目录设置位置描述（左栏侧边栏） |
| desktop/server.py | NEW `POST /api/config/pick`：调 PowerShell `FolderBrowserDialog`（STA）弹原生文件夹选择框，初始目录为当前输出目录，UTF-8 输出选中路径（取消返回 `cancelled`），180s 超时兜底 |
| desktop/web/index.html | 侧边栏 EPUB 输出目录新增「选择文件夹…」按钮：点击弹系统对话框，选中后填入输入框，点「保存」生效 |

### 验证
- PowerShell 对话框脚本构造/初始路径传递正常；真实弹窗可打开（实测进程存活）。
- monkeypatch `subprocess.run` 直测 `_config_pick`：选中路径/取消两种分支 JSON 均正确（UTF-8 中文路径往返无损）。
- node 语法检查 + 119 单测全过；冻结 exe 重建（40.6MB）页面含新按钮，config 正常。

## Round 2026-07-31 (7) — FIX: 选择文件夹对话框不弹出

| Area | Change |
| --- | --- |
| desktop/server.py | FIX: 原实现 spawn PowerShell `FolderBrowserDialog`（子进程 + .NET Add-Type），冻结 exe 环境下对话框窗口根本不出现（实测子进程存活但 MainWindowTitle 为空）。改为进程内原生 Win32 `IFileDialog`（ctypes COM 直调，同 `os.startfile` 一样无子进程）：`FOS_PICKFOLDERS` + 自定义标题 + `SetFolder` 初始目录 + `GetResult`/`GetDisplayName(SIGDN_FILESYSPATH)` + `CoTaskMemFree` |
| desktop/server.py | 修两处坑：IShellItem IID 应为 `43826d1e-e718-42ee-bc55-a1e261c37bfe`（误写 bc45-…e977 导致 E_NOINTERFACE）；HRESULT 用有符号 `c_long` 比较（E_CANCEL = 0x800704C7 需转有符号）；`SetDefaultFolder` 在有历史状态时不生效 → 改 `SetFolder` |

### 验证
- 真实弹窗实测：对话框出现（标题「选择 EPUB 输出目录」），取消 → `cancelled:true`；确认 → 返回默认输出目录 `C:\Users\plague doctor\.mybooks_book_source\books`；冻结 exe 同流程复测通过。
- 119 单测全过；冻结 exe 重建（40.6MB）冒烟正常。

---

## Round 2026-08-01 (8) — MyBooks 插件化 + 真实接口集成验证（L3 + L2a）

> **重要修正（推翻上方 File Map 的旧假设）**：目标 `mybooks-3.49.0` 源码核对证实——
> ① `webserver/handlers/toolbox.py` 现存约 14 条路由，**没有任何 book_source 路由**，旧表假设「handler 已存在、无需改动」不成立；
> ② 目标仓库（含用户 fork 各 v3.x 分支）从未部署过任何 book_source 文件；
> ③ 引擎 4 个核心模块（rule_engine/epub_helper/content_fallbacks/search_task_service）本身已是「相对导入优先 + standalone 兜底」双模式，插件化无需改导入，只有测试与 CLI 需要转换。

### 新增：`书源引擎插件/`（与桌面版共用引擎代码）

| 文件 | 说明 |
| --- | --- |
| `webserver/handlers/book_source_api.py` | **新增 14 个 handler**（全部 `@js + @is_admin`），导出 `BOOK_SOURCE_ROUTES`：list/save/toggle/delete/search_async/search_status/test/download/generate_epub/cancel/progress/import_zip/import_url/download_epub |
| `webserver/handlers/toolbox.py` | 目标文件修改版：+1 import（`BOOK_SOURCE_ROUTES`）+ `routes()` 末尾 `] + BOOK_SOURCE_ROUTES` |
| `webserver/toolbox/toolset.py` | 目标文件修改版：`collect_tools()` 内 `from .book_source_tool import BookSourceTool` + `ToolSet.register(BookSourceTool.info())` |
| `webserver/toolbox/book_source_engine/` | 引擎包 7 文件（与桌面版同源） |
| `webserver/toolbox/book_source_tool.py` | 工具类：`service_item_name="书源管理"`，`TOOL_DATA_ROOT/<tool_id>/sources.json` 存储，`get_work_dir` 复用目标 BaseTool 基建 |
| `app/pages/toolbox/book_source.vue` | 管理页（Nuxt 自动路由，无需改 router） |
| `locales/{zh,en,zh-TW}.json` | `bookSource` 68 键片段 |
| `tools/merge_locales.py` | 幂等合并片段进目标 `app/locales/*` |
| `tools/integration_smoke.py` | 集成冒烟（18 用例，需目标源码树） |
| `tests/test_book_source_engine.py` | 119 用例（包导入版） |

### 修复（L2a 中发现）

| 文件 | 修复 |
| --- | --- |
| `book_source_engine/js_runtime.py` | `import dukpy` 无条件顶层导入 → 无 dukpy 时整个引擎包无法导入。改为 try/except + `_HAS_DUKPY` 标志，`_get_interp` 缺失时抛 `JsRuleUnsupported`；**已同步桌面 `构建产物/standalone_build/js_runtime.py`** |
| `tests/test_book_source_engine.py` | `TestJsRuntime`/`TestLegadoWithJs` 加 `@skipUnless(_HAS_DUKPY)`（与 README 声称一致） |
| `handlers/book_source_api.py` | save 校验 `raw` 必须含非空 `bookSourceName`（`{}` 此前会静默建空源） |

### L2a 真实接口集成验证（临时 venv，非 stub）

环境：真实目标文件（models/i18n/loader/handlers/base/toolbox/toolset/base_tool/services/*）+ 插件文件 + 最小依赖（tornado/jinja2/sqlalchemy/pymupdf/pillow 等；`social_sqlalchemy` PyPI 无包 → 仅测试桩）。已核实：**所有 calibre 引用均为函数内懒加载**，本机无需 calibre 即可验证接口层。

- 119 单元测试全过（含 dukpy JS 用例真跑）。
- 18 项冒烟全过：真实 `BaseTool.create_task→update_task_progress→complete_task→get_last_task` 链路、任务失败/取消、书源 CRUD、`ToolSet` 注册（`/api/toolbox/list` 含 book_source）、27 条路由挂载（13+14）、14 条 book_source 端点响应契约（`err:"ok"` / `book_source.not_found` / `params.missing` / `import_failed` / `task.not_found` / epub 404）、真实 AsyncService 线程池任务执行。
- 冒烟中踩过的坑（均属测试环境而非插件）：tornado `current_user` 缓存需重写 property、`BaseHandler.initialize` 需要 `ScopedSession/legacy/build_time/default_cover` settings、`AsyncService().setup(None, scoped)` 必须预置真实 scoped_session（否则服务线程 `.hash_key` 崩）。

### 部署清单（PR）

1. 引擎包 → `webserver/toolbox/book_source_engine/`（新增）
2. `book_source_tool.py` → `webserver/toolbox/`（新增）
3. `book_source_api.py` → `webserver/handlers/`（新增）
4. `toolbox.py`：2 处（import + routes 尾部追加）
5. `toolset.py`：2 处（collect_tools import + register）
6. `book_source.vue` → `app/pages/toolbox/`（新增）
7. locales：`python tools/merge_locales.py <mybooks-root>`
8. `requirements.txt`：**追加 `dukpy>=0.4.0`（必须）**；其余依赖目标已具备

### 验证
- 119 单测 + 18 冒烟全过（见上）；`py_compile` 全过。
- 真机端到端（docker + calibre 库）不在本机可测范围 → 以 L2a 接口验证 + 部署清单替代，部署后建议跑 `tests/integration_smoke.py`。

---

## Round 2026-08-01 �� PR #43 ���ύ�� PoxenStudio/mybooks

| �� | ��� |
| --- | --- |
| PR | https://github.com/PoxenStudio/mybooks/pull/43��state: open��mergeable: clean�� |
| ���� | develop HEAD e1147268��= v4.0.1 ���� + 2 �ύ������֧ feat/book-source-engine @ c92e5aa1 |
| ��֤ | L2a �����ؽ�Ϊ develop ��119 ���� + 18 ð��ȫ�̣������ļ������ո��飩 |
| ����ļ� | 20 ����14 ���� + 6 �޸ģ�toolbox.py +2/-1��toolset.py +2/-0��requirements.txt +4/-1��locales �� +71/-1������ +6519/-5 |
| �ؼ����� | �� ���� develop �ش򲹶���v3.49 ���������� mimo_tts/bookbarn �ȹ��ߣ��� vue ��λ�� app/src/pages/toolbox/��Nuxt srcDir=src/���� dukpy>=0.4.0 ����Ϊ dukpy==0.6.0��0.4.0 �����ڣ�0.6.0 �� cp39-314 ȫƽ̨ wheel����Ӱ�� docker �������� ���з� CRLF��LF ���� diff ���� �� tests/ �� PR ������ CI ���� |
| README | ��� README + ���� README ������talebook BSD-2-Clause ��������������·����dukpy �� Docker Ӱ��˵�� |
| ��ע | shiningsprk-arch/mybooks Ϊ�Զ� fork��mybooks-book-source ͬ���� Round 8 �ύ���� |

---

## Round 2026-08-01 (2) �� PR #43 �ѹرգ����߲��ϲ���Դ���ܣ�

| �� | ��� |
| --- | --- |
| PR #43 | state=closed��closed_at 2026-08-01T04:18:33Z����δ׷������ |
| ��֧ | fork �� feat/book-source-engine ��ɾ������֤ 404����fork �ֿⱣ�� |
| ԭ�� | ����˽�¹�ͨ����Դ���ܶ�λ��̫�ʺ����ߺϲ� |
| ����ȥ�� | ȫ���ɹ�������shiningsprk-arch/mybooks-book-source��main @ cc05d257��74 ��Ŀ����+ ���ز��Ŀ¼ + ���������֤���ߣ�develop������Ի����� Temp Ŀ¼�ɸ��� |
| ����ѡ�� | ���ò���README �����嵥 8 �� / ���� README������ fork ��֧�������� |

---

## Round 2026-08-01 (3) �� �ֿ����

| �� | ��� |
| --- | --- |
| ���� | shiningsprk-arch/mybooks-book-source |
| ���� | shiningsprk-arch/book-source-engine��GitHub �Զ��ض�������ӣ� |
| README | ����������£��������ö�λ + �����/�����˵�� + PR #43 δ�ϲ�˵�� |
| ���� | mybooks-book-source-app.spec��exe ����������CHANGESET ��ʷ��¼���������ﲻ�� |
