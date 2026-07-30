# MyBooks Book Source Plugin

为 [MyBooks](https://github.com/talebook/talebook) 工具箱提供的书源管理插件，兼容 Legado 3.0 书源格式。

## 功能

- 书源 CRUD 管理（添加/编辑/删除/导入/导出）
- Legado 3.0 规则引擎（CSS / JSONPath / XPath / Legado 简写选择器 / JS 运行时）
- 多书源异步并发搜索（ThreadPoolExecutor，最长 300s 超时）
- 书籍详情 / 目录 / 正文抓取（支持分页）
- EPUB 生成 & Calibre 自动入库
- 书源连通性校验 & 兼容性自动检测
- 分类浏览（Explore）
- Vue 管理页面

## 用法

作为 MyBooks 插件加载后，在工具箱中可见「书源管理」工具。支持：

- 在 `/toolbox/book_source/` 管理书源
- 在任意搜索框使用「全部书源」模式并发检索
- 一键导入 Legado 3.0 JSON 格式书源

## 致谢

书源规则引擎参考了 [talebook/talebook](https://github.com/talebook/talebook) 的书源实现。

## 许可证

MIT
