# MyBooks Book Source — 书源管理插件

## 概述

为 MyBooks Toolbox 提供书源管理功能，兼容 Legado 3.0 JSON 格式的书源规则。
支持书源的 CRUD、搜索、测试、正文下载、EPUB 生成、Calibre 入库。

## 文件清单

| 文件 | 说明 |
|------|------|
| `book_source_model.py` | Legado 3.0 兼容数据模型 |
| `rule_engine.py` | 规则引擎（CSS / JSONPath / XPath / Legado / JS） |
| `js_runtime.py` | 受限 JS 运行时（基于 dukpy） |
| `content_fallbacks.py` | 站点级内容获取回退处理器 |
| `epub_helper.py` | EPUB 生成模块（独立可复用） |
| `generate_epub.py` | CLI 封装（可直接命令行调用） |
| `book_source_tool.py` | MyBooks Toolbox 集成工具类 |
| `book_source.vue` | Vue 管理页面 |
| `sample_sources.json` | 3 个示例书源 |
| `deqixs_test.json` | 得奇小说测试书源 |
| `test_rule_engine.py` | 109 个单元测试 |
| `PLAN.md` | 开发计划 |
| `PR.md` | PR 提交指南 |

## 引擎能力

| 特性 | 状态 |
|------|------|
| CSS 选择器 | ✅ |
| JSONPath | ✅ 自定义引擎 |
| XPath | ✅ 基础支持 |
| `class.xxx` / `id.xxx` / `tag.xxx` / `text.xxx` Legado 简写 | ✅ 移植自 talebook |
| 多步 `@` 链式选择器 | ✅ |
| 索引语法 (`.0`, `[1]`, `[1:3:5]`, 负索引) | ✅ |
| `@textNodes` / `@owntext` 属性提取 | ✅ |
| `##pattern##replacement` 尾部正则 | ✅ |
| `@js:result.replace()` JS 后处理 | ✅ dukpy |
| `jsLib` 用户自定义函数 | ✅ |
| `<js>` 块 / `java.ajax()` / `java.getString()` | ❌ 触发 `JsRuleUnsupported` |
| header JSON 字符串自动解析 | ✅ |
| searchUrl (POST/body/charset) | ✅ |
| 内容获取 fallback | ✅ content_fallbacks.py |
| EPUB 生成 | ✅ 封面 / 目录 / 章节 / Calibre 就绪 |

## 使用方式

### 命令行 CLI

```bash
python generate_epub.py 捞尸人 50
```

### MyBooks Toolbox 集成

书源工具注册后可在 Toolbox 界面中使用。

## 单元测试

```bash
python test_rule_engine.py -v
```

预期 109 个测试全部通过。
