# 书源引擎（MyBooks 插件版）

「书源引擎」是 MyBooks 工具箱（Toolbox）的书源管理插件：支持 Legado 3.0 兼容规则解析、
多书源异步搜索、分类浏览（Explore）、正文抓取与 EPUB 生成，内置反爬层与安全加固。

本目录是**插件版**（可部署到 MyBooks），与桌面版（exe）共用同一份引擎代码；
引擎模块采用「相对导入优先、standalone 兜底」的双模式写法，
同一份文件既可打包进桌面版，也可作为 `book_source_engine` 包运行。

## 目录结构（对应 MyBooks 目标路径）

```
书源引擎插件/
├── webserver/toolbox/book_source_engine/
│   ├── __init__.py              # 包导出（含 fetch_explore / parse_explore_categories）
│   ├── book_source_model.py     # 规则数据模型（init / nextTocUrl 字段）
│   ├── rule_engine.py           # 规则解析引擎（CSS/JSONPath/XPath/Legado/JS + 反爬层）
│   ├── js_runtime.py            # dukpy JS 沙箱（LRU 解释器缓存 / 无界循环防护）
│   ├── content_fallbacks.py     # 内容抓取兜底（复用反爬 session）
│   ├── epub_helper.py           # EPUB 生成（内嵌图片、封面不落盘）
│   └── search_task_service.py   # 单例异步多源搜索（ThreadPoolExecutor + 轮询）
├── webserver/toolbox/book_source_tool.py   # 工具箱工具（CRUD/验证/异步搜索/EPUB 任务）
├── app/pages/toolbox/book_source.vue       # 管理页面（搜索下载 + 书源管理双标签）
├── locales/
│   ├── zh.json / en.json / zh-TW.json      # bookSource 国际化片段（合并到 app/locales/*）
├── tests/
│   ├── test_book_source_engine.py          # 119 个单元测试（包导入版）
│   └── data/
│       ├── sample_sources.json             # 3 个示例书源
│       └── deqixs_test.json                # 得奇小说测试夹具
└── tools/
    └── generate_epub.py                    # 独立 CLI（包导入优先，standalone 兜底）
```

## 部署到 MyBooks

1. **引擎包**：将 `webserver/toolbox/book_source_engine/` 整体复制到
   `mybooks-3.49.0/webserver/toolbox/`（目录不存在则新建）。
2. **工具箱工具**：将 `book_source_tool.py` 复制到 `webserver/toolbox/`，
   并在 `webserver/toolbox/__init__.py` 注册：

   ```python
   from webserver.toolbox.tools.book_source_tool import BookSourceTool  # 或按目标仓库的注册方式
   ```

3. **管理页面**：将 `book_source.vue` 放到 `app/pages/toolbox/`，并按目标
   `app/src/router` 增加工具箱路由。
4. **国际化**：把 `locales/*.json` 的 `bookSource` 片段合并进
   `app/locales/zh.json`、`en.json`、`zh-TW.json`（顶层新增 `bookSource` 键）。
5. **依赖**（加入 requirements.txt）：`beautifulsoup4>=4.12`、`lxml>=5.0`、
   `requests>=2.31`、`dukpy>=0.4.0`、`ebooklib>=0.18`；
   可选反爬增强：`curl_cffi`（Chrome TLS 指纹）。

## 运行测试

```bash
# 在插件目录内（webserver 包位于插件根下）
cd 书源引擎插件
python -m unittest discover -s tests -p "test_*.py" -v

# 或在 MyBooks 源码树内（部署后）
cd mybooks-3.49.0
python -m unittest tests.test_book_source_engine -v
```

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
