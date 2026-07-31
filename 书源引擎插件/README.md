# 书源引擎（MyBooks 插件版）

「书源引擎」是 MyBooks 工具箱（Toolbox）的书源管理插件：支持 Legado 3.0 兼容规则解析、
多书源异步搜索、分类浏览（Explore）、正文抓取与 EPUB 生成，内置反爬层与安全加固。

本目录是**插件版**（可部署到 MyBooks），与桌面版（exe）共用同一份引擎代码；
引擎模块采用「相对导入优先、standalone 兜底」的双模式写法，
同一份文件既可打包进桌面版，也可作为 `book_source_engine` 包运行。

## 目录结构（对应 MyBooks 目标路径）

```
书源引擎插件/
├── webserver/handlers/
│   ├── book_source_api.py         # 14 个 API handler（新增，对应下方路由表）
│   └── toolbox.py                 # 目标文件修改版：+1 import、routes() 追加 BOOK_SOURCE_ROUTES
├── webserver/toolbox/
│   ├── book_source_engine/
│   │   ├── __init__.py            # 包导出（含 fetch_explore / parse_explore_categories）
│   │   ├── book_source_model.py   # 规则数据模型（init / nextTocUrl 字段）
│   │   ├── rule_engine.py         # 规则解析引擎（CSS/JSONPath/XPath/Legado/JS + 反爬层）
│   │   ├── js_runtime.py          # dukpy JS 沙箱（LRU 解释器缓存 / 无界循环防护）
│   │   ├── content_fallbacks.py   # 内容抓取兜底（复用反爬 session）
│   │   ├── epub_helper.py         # EPUB 生成（内嵌图片、封面不落盘）
│   │   └── search_task_service.py # 单例异步多源搜索（ThreadPoolExecutor + 轮询）
│   ├── book_source_tool.py        # 工具箱工具（CRUD/验证/异步搜索/EPUB 任务）
│   └── toolset.py                 # 目标文件修改版：collect_tools() +1 注册
├── app/pages/toolbox/book_source.vue       # 管理页面（搜索下载 + 书源管理双标签）
├── locales/
│   ├── zh.json / en.json / zh-TW.json      # bookSource 国际化片段（合并到 app/locales/*）
├── tests/
│   ├── test_book_source_engine.py          # 119 个单元测试（包导入版）
│   └── data/
│       ├── sample_sources.json             # 3 个示例书源
│       └── deqixs_test.json                # 得奇小说测试夹具
└── tools/
    ├── generate_epub.py                    # 独立 CLI（包导入优先，standalone 兜底）
    ├── merge_locales.py                    # i18n 合并脚本（幂等）
    └── integration_smoke.py                # 集成冒烟（需目标源码树，见下）
```

## 部署到 MyBooks（PR 集成清单）

对 `mybooks-3.49.0` 目标仓库（v3.49.0，与 v3.27.1 分支结构相同）做以下改动：

| # | 目标文件 | 改动 |
| --- | --- | --- |
| 1 | `webserver/toolbox/book_source_engine/` | 新增目录（7 个文件） |
| 2 | `webserver/toolbox/book_source_tool.py` | 新增文件 |
| 3 | `webserver/handlers/book_source_api.py` | 新增文件（14 个 handler，全部 `@js + @is_admin`） |
| 4 | `webserver/handlers/toolbox.py` | 2 处：`from webserver.handlers.book_source_api import BOOK_SOURCE_ROUTES`；`routes()` 末尾 `] + BOOK_SOURCE_ROUTES` |
| 5 | `webserver/toolbox/toolset.py` | 2 处：`collect_tools()` 内 import + `ToolSet.register(BookSourceTool.info())` |
| 6 | `app/pages/toolbox/book_source.vue` | 新增文件（Nuxt 自动路由，无需改 router） |
| 7 | `app/locales/{zh,en,zh-TW}.json` | 顶层新增 `bookSource` 键：`python tools/merge_locales.py <mybooks-root>` |
| 8 | `requirements.txt` | 追加 `dukpy>=0.4.0`（**必须**，JS 规则依赖）；其余 `requests/bs4/lxml/EbookLib/chardet` 目标仓库已具备 |

### API 路由表（`/api/toolbox/book_source/...`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `list` | 书源列表 |
| POST | `save` | 新增/更新书源（body: `{raw}`） |
| POST | `toggle` | 启用/停用（body: `{name}`） |
| POST | `delete` | 删除（body: `{name}`） |
| POST | `search_async` | 异步多源搜索（body: `{keyword}`） |
| GET | `search_status?task_id=` | 搜索进度与结果 |
| GET | `test?source=` | 单源连通性测试 |
| POST | `download` | 下载书籍（body: `{source, bookUrl, bookTitle, maxChapters}`） |
| POST | `generate_epub` | EPUB 生成任务 |
| POST | `cancel` | 取消后台任务（body: `{task_id}`） |
| GET | `progress` | 最近任务进度（`data:{task_id, progress, status, progress_data}`） |
| POST | `import_zip` | 上传 zip 导入书源（multipart `file`） |
| POST | `import_url` | 从 URL 导入书源（body: `{url}`） |
| GET | `download_epub` | 下载最近生成的 EPUB（`application/epub+zip`） |

## 运行测试

```bash
# 在插件目录内（webserver 包位于插件根下）
cd 书源引擎插件
python -m unittest discover -s tests -p "test_*.py" -v

# 或在 MyBooks 源码树内（部署后）
cd mybooks-3.49.0
python -m unittest tests.test_book_source_engine -v
```

> 注意：若 Python 3.13 环境装不上 `dukpy`（尚无对应 wheel），JS 规则相关
> 用例将自动跳过（`skipUnless`），其余用例不受影响；完整运行请用 Python ≤3.12。

## 集成冒烟（可选，验证 PR 兼容性）

在 MyBooks 源码检出根目录运行（无需 calibre，所有 calibre 引用均为函数内懒加载）：

```bash
cd mybooks-3.49.0
python tests/integration_smoke.py     # 或工具目录：python tools/integration_smoke.py
```

覆盖：真实 `BaseTool` 任务生命周期、书源 CRUD、`ToolSet` 注册、
14 条 book_source 路由的 `{"err": "ok"}` 响应契约（18 项用例）。

## 引擎特性

- **规则解析**：`@css:` 前缀、`||` / `&&` / `%%` 组合符、`@put:` / `@get:` 变量、
  多页目录（`nextTocUrl`）与多页正文（`nextContentUrl`）、Explore 分类浏览。
- **反爬层**（算法更新）：UA 轮换池、浏览器风格请求头（Sec-Fetch-*）、
  请求间隔抖动、状态感知重试（429 Retry-After / 403+5xx 退避换 UA）、
  代理支持（`MYBOOKS_PROXY`）、可选 curl_cffi Chrome TLS 指纹（`MYBOOKS_HTTP_BACKEND`）、
  chardet 解码、零宽字符清洗。
- **安全加固**（review）：SSRF 防护（拒绝内网/回环 URL）、多用户任务隔离、
  书源文件读写锁、EPUB 图片按章节唯一命名、封面不落盘、Legado 开区间索引越界防护、
  jsLib 无界循环拒绝执行。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `MYBOOKS_HTTP_BACKEND` | `curl_cffi`（Chrome TLS 指纹，需安装）或 `requests` |
| `MYBOOKS_PROXY` | HTTP(S) 代理地址 |
| `MYBOOKS_FETCH_DELAY` | 抓取间隔抖动（秒，默认 0.3） |
| `MYBOOKS_FETCH_JITTER` | 抖动幅度（默认 0.5） |
