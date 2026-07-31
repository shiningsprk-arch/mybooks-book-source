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
