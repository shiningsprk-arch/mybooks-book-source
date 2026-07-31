# MyBooks Book Source — PR 提交指南

## 提交内容

本 PR 为 MyBooks Toolbox 添加书源管理功能，包含：

### 核心引擎（独立可复用）
  `book_source_model.py` — Legado 3.0 兼容数据模型
  `rule_engine.py` — 规则引擎（CSS / JSONPath / XPath / Legado / JS）
  `js_runtime.py` — 受限 JS 运行时（基于 dukpy）
  `content_fallbacks.py` — 站点级内容获取回退处理器
  `epub_helper.py` — EPUB 生成模块

### Toolbox 集成
  `book_source_tool.py` — BaseTool 子类，注册为工具
  `book_source.vue` — Vue 管理页面

### 辅助文件
  `sample_sources.json` — 3 个示例书源
  `deqixs_test.json` — 得奇小说测试书源
  `test_rule_engine.py` — 109 个单元测试
  `generate_epub.py` — CLI 封装
  `preview/index.html` — 独立预览页
  `PLAN.md` / `PR.md` — 文档

## 安装依赖

```bash
pip install beautifulsoup4 lxml requests dukpy ebooklib
```

dubpy 需要 pre built wheel：

```bash
pip install dukpy   only binary :all:
```

## 集成步骤

1. 将 `book_source_tool.py` 放入 `webserver/toolbox/tools/` 目录
2. 将 `book_source.vue` 放入 `webserver/toolbox/tools/book_source/` 目录
3. 将核心模块（`book_source_model.py`, `rule_engine.py`, `js_runtime.py`, `content_fallbacks.py`, `epub_helper.py`）放入 Python 可搜索路径
4. 在 `webserver/toolbox/__init__.py` 中注册工具

## 注册示例

```python
# webserver/toolbox/__init__.py
from webserver.toolbox.tools.book_source_tool import BookSourceTool
register_tool(BookSourceTool)
```

## 注意事项

  dukpy 没有 C 扩展编译问题，有 pre built wheel
  content_fallbacks.py 使用 `@register(domain_pattern)` 装饰器注册处理器
  新站点只需添加新的 `@register` 函数即可支持
  EPUB 生成依赖 ebooklib（`pip install ebooklib`）
