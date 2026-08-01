# book-source-engine

基于 Legado 3.0 规则格式的书源引擎与书源工具（MyBooks 插件版 + 独立桌面版）。

- **规则引擎**：解析 Legado 兼容书源（CSS / JSONPath / XPath / 正则 / URL 模板 / Legado 选择器），提供搜索、书籍详情、目录、正文抓取、分类浏览能力。
- **内容 fallback**：对 `@js:` 规则失败的站点（如得奇小说 deqixs）提供 Python 级模拟请求链。
- **EPUB 生成**：抓取正文内嵌图片、封面，生成标准 EPUB。
- **MyBooks 插件版**：`书源引擎插件/` 目录为完整插件包（引擎 + Toolbox 工具 + 14 条 API 路由 + 管理页面），部署清单见该目录 README。
- **桌面版**：零依赖本地 Web UI（书源管理 / 多源搜索 / EPUB 生成），可打包为单文件 exe。

> 说明：本项目此前曾以 PR 提交至 [PoxenStudio/mybooks](https://github.com/PoxenStudio/mybooks)（PR #43），
> 经与作者沟通后未合并（书源功能暂不适合主线），现作为独立自用项目维护。

## 快速开始（桌面版）

```bash
python desktop/run.py            # 开发模式，自动打开 http://127.0.0.1:8756/
python -m PyInstaller mybooks-book-source-app.spec   # 打包 exe
```

数据目录（书源与配置）：`~/.mybooks_book_source/`，可用环境变量 `MYBOOKS_BS_DATA` 覆盖。
EPUB 输出目录可在页面左侧边栏设置（输入路径，或点「选择文件夹…」弹出系统文件夹对话框）。

## 系统要求（Windows 桌面版 exe）

- **系统**：64 位 Windows 10 / 11。无需安装 Python，无需安装 VC++ 运行库（均已内置）。
- **网络**：搜索与抓取书源内容需要联网。
- **权限**：无需管理员权限；数据只写入 `%USERPROFILE%\.mybooks_book_source\`，仅监听本机 `127.0.0.1`。
- 首次运行可能被 Windows SmartScreen 拦截（exe 未签名）：点「更多信息」→「仍要运行」即可。
- 启动后请保持黑色控制台窗口开启（关闭它服务即退出）。

## 反爬虫规避

抓取层内置多项反爬规避（参考 talebook 书源模块的请求头与正文清理思路，见下方版权声明）：

- **UA 轮换**：内置多个浏览器 UA 池，会话级随机轮换，规避单一 UA 指纹。
- **浏览器风格请求头**：`Accept` / `Accept-Language` / `Accept-Encoding` / `Sec-Fetch-*` 等。
- **随机节流抖动**：固定延时 + 随机抖动，避免固定间隔指纹。
- **状态感知重试**：429 按 `Retry-After` 等待；403 / 5xx 换 UA 后指数退避重试。
- **可选 TLS 指纹伪装**：若安装 `curl_cffi`，自动用 Chrome TLS 指纹请求；否则回退 `requests`。
- **代理支持**：环境变量 `MYBOOKS_PROXY` 设置 http/https 代理。
- **正文清理**：去除零宽字符（U+200B/U+200C/U+200D/U+FEFF）、统一换行、折叠多空行。

相关环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MYBOOKS_HTTP_BACKEND` | `auto` | `requests` 强制退用 requests；`curl_cffi` 强制用 curl_cffi |
| `MYBOOKS_FETCH_DELAY` | `0.2` | 请求间基础延时（秒），`0` 关闭 |
| `MYBOOKS_FETCH_JITTER` | `0.15` | 额外随机抖动上限（秒） |
| `MYBOOKS_FETCH_RETRIES` | `2` | 失败重试次数 |
| `MYBOOKS_HTTP_TIMEOUT` | `30` | 请求超时（秒） |
| `MYBOOKS_PROXY` | — | 代理地址，如 `http://127.0.0.1:7890` |
| `MYBOOKS_BS_DATA` | `~/.mybooks_book_source` | 数据目录 |

## 测试

```bash
python -X utf8 "书源引擎插件/tests/test_book_source_engine.py" -v
```

引擎源码与测试均位于 `书源引擎插件/`（`webserver/toolbox/book_source_engine/`）。

## 版权声明

本项目书源模块的请求头规范、正文清理思路（零宽字符 / 换行规整）参考并部分借用了
**[talebook](https://github.com/talebook/talebook)** 的
[书源引擎](https://github.com/talebook/talebook/tree/master/webserver/services/booksource)
实现（BSD-2-Clause 协议，见其 [LICENSE](https://github.com/talebook/talebook/blob/master/LICENSE)）。

talebook 部分代码在 BSD-2-Clause 许可下使用，版权归其原作者所有。
本项目其余代码遵循 MIT License。
