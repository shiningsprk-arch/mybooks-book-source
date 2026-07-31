"""
test_rule_engine — 书源规则引擎单元测试。

覆盖:
  - CSS 选择器
  - JSONPath 引擎
  - Legado 选择器（移植自 talebook fork）
  - Header 解析 / searchUrl 解析
  - JS 运行时 (dukpy)
  - content fallback 机制
  - 完整搜索→详情→目录→正文流程
"""

import json
import os
import sys
import tempfile
import unittest
from typing import Any

# ── 将被测模块加入路径 ──────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from book_source_model import (
    BookSource, RuleSearch, RuleBookInfo, RuleToc, RuleContent,
    load_sources_from_json, dump_sources_to_json,
)
from rule_engine import (
    parse_selector, css_select_one, css_select_all,
    parse_source_header,
    legado_select, legado_extract_one, legado_extract_from_element,
    legado_extract_list,
    JsonPathEngine,
    render_url_template, extract_single, extract_list,
    search_books, fetch_book_info, fetch_toc, fetch_content,
    _parse_search_url, apply_replace_rules,
    fetch_url, is_json_content, guess_response_type,
)
from js_runtime import run_js, JsRuleUnsupported


# ═════════════════════════════════════════════════════════════════
# HTML 测试数据
# ═════════════════════════════════════════════════════════════════

HTML_BOOK_LIST = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<ul class="book-list">
  <li>
    <h3 class="title"><a href="/book/1">书名A</a></h3>
    <p class="author">作者A</p>
    <span class="status">连载中</span>
    <img class="cover" src="/cover/a.jpg" alt="封面A"/>
  </li>
  <li>
    <h3 class="title"><a href="/book/2">书名B</a></h3>
    <p class="author">作者B</p>
    <span class="status">已完结</span>
    <img class="cover" src="/cover/b.jpg" alt="封面B"/>
  </li>
</ul>
</body>
</html>"""

HTML_TOC = """<!DOCTYPE html>
<html>
<body>
<div id="list">
  <dl>
    <dd><a href="/c/1">第一章 开始</a></dd>
    <dd><a href="/c/2">第二章 发展</a></dd>
    <dd><a href="/c/3">第三章 高潮</a></dd>
  </dl>
</div>
</body>
</html>"""

HTML_CONTENT = """<!DOCTYPE html>
<html>
<body>
<div id="content">
<p>这是正文第一段。</p>
<p>这是正文第二段。</p>
</div>
</body>
</html>"""

HTML_DETAIL = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<div class="book-info">
  <h1 class="bookname">书名A</h1>
  <p class="author"><a href="/author/1">作者A</a></p>
  <p class="chapter"><a href="/last">最新章</a></p>
  <div class="intro">书籍简介内容</div>
  <img class="bookcover" src="/cover/a.jpg"/>
  <div id="status">
    <span>字数：1234567</span>
  </div>
</div>
</body>
</html>"""

# Legado 风格 HTML
HTML_LEGADO = """<!DOCTYPE html>
<html>
<body>
<div class="bookcase">
  <li>
    <div class="bookcover"><img src="/cover/1.jpg"/></div>
    <div class="bookname"><a href="/book/1">测试书名</a></div>
    <div class="author">测试作者</div>
    <div class="updata"><a href="/last/1">最新章1</a></div>
  </li>
  <li>
    <div class="bookcover"><img src="/cover/2.jpg"/></div>
    <div class="bookname"><a href="/book/2">测试书名2</a></div>
    <div class="author">测试作者2</div>
    <div class="updata"><a href="/last/2">最新章2</a></div>
  </li>
</div>
</body>
</html>"""

# JSON 测试数据
JSON_BOOK_LIST = {
    "data": {
        "books": [
            {"title": "书名A", "author_name": "作者A",
             "chapter_count": 100, "cover": "/a.jpg"},
            {"title": "书名B", "author_name": "作者B",
             "chapter_count": 200, "cover": "/b.jpg"},
        ]
    },
    "total": 2,
}


# ═════════════════════════════════════════════════════════════════
# 解析器测试
# ═════════════════════════════════════════════════════════════════

class TestParseSelector(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_selector("")["type"], "skip")
        self.assertEqual(parse_selector("  ")["type"], "skip")

    def test_css_simple(self):
        r = parse_selector("div.title")
        self.assertEqual(r["type"], "css")
        self.assertEqual(r["selector"], "div.title")
        self.assertEqual(r["attr"], "text")

    def test_css_with_attr(self):
        r = parse_selector("div.title@href")
        self.assertEqual(r["type"], "css")
        self.assertEqual(r["attr"], "href")

    def test_css_with_index(self):
        r = parse_selector("div.title@href.2")
        self.assertEqual(r["index"], 2)

    def test_jsonpath(self):
        r = parse_selector("$.data.books")
        self.assertEqual(r["type"], "jsonpath")
        r2 = parse_selector("$['data']")
        self.assertEqual(r2["type"], "jsonpath")

    def test_xpath(self):
        r = parse_selector("//div[@class='title']")
        self.assertEqual(r["type"], "xpath")
        r2 = parse_selector("xpath://div")
        self.assertEqual(r2["type"], "xpath")

    def test_regex(self):
        r = parse_selector("/pattern/")
        self.assertEqual(r["type"], "regex")
        self.assertEqual(r["pattern"], "pattern")

    def test_legado_shorthand(self):
        r = parse_selector("class.title")
        self.assertEqual(r["type"], "legado")
        r2 = parse_selector("id.content")
        self.assertEqual(r2["type"], "legado")
        r3 = parse_selector("tag.div")
        self.assertEqual(r3["type"], "legado")

    def test_legado_chain(self):
        r = parse_selector("class.bookcase@li@a@text")
        self.assertEqual(r["type"], "legado")

    def test_js_template(self):
        r = parse_selector("{{result.replace('a','b')}}")
        self.assertEqual(r["type"], "js")


# ═════════════════════════════════════════════════════════════════
# CSS 选择器测试
# ═════════════════════════════════════════════════════════════════

class TestCssSelector(unittest.TestCase):
    def test_select_one_text(self):
        result = css_select_one("ul.book-list li:first-child h3.title", HTML_BOOK_LIST)
        self.assertIsNotNone(result)
        self.assertIn("书名A", result or "")

    def test_select_one_href(self):
        result = css_select_one("ul.book-list li:first-child h3.title a@href", HTML_BOOK_LIST)
        self.assertEqual(result, "/book/1")

    def test_select_one_src(self):
        result = css_select_one("ul.book-list li:first-child img.cover@src", HTML_BOOK_LIST)
        self.assertEqual(result, "/cover/a.jpg")

    def test_select_all_count(self):
        results = css_select_all("ul.book-list li", HTML_BOOK_LIST)
        self.assertEqual(len(results), 2)

    def test_select_nonexistent(self):
        result = css_select_one("div.not-exist", HTML_BOOK_LIST)
        self.assertIsNone(result)

    def test_invalid_css(self):
        result = css_select_one("{{{invalid}}}", HTML_BOOK_LIST)
        self.assertIsNone(result)


# ═════════════════════════════════════════════════════════════════
# JSONPath 引擎测试
# ═════════════════════════════════════════════════════════════════

class TestJsonPathEngine(unittest.TestCase):
    def test_simple_key(self):
        data = {"name": "test", "value": 42}
        result = JsonPathEngine.query(data, "$.name")
        self.assertEqual(result, ["test"])

    def test_nested_key(self):
        result = JsonPathEngine.query(JSON_BOOK_LIST, "$.data.books")
        # books is a list, _eval at leaf returns [list], so one serialized result
        self.assertEqual(len(result), 1)
        parsed = json.loads(result[0])
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["title"], "书名A")

    def test_array_index(self):
        result = JsonPathEngine.query(JSON_BOOK_LIST, "$.data.books[0].title")
        self.assertEqual(result, ["书名A"])

    def test_slice(self):
        result = JsonPathEngine.query(JSON_BOOK_LIST, "$.data.books[0:1].title")
        self.assertEqual(len(result), 1)

    def test_wildcard(self):
        data = {"items": [{"x": 1}, {"x": 2}]}
        result = JsonPathEngine.query(data, "$.items[*].x")
        self.assertEqual(set(result), {"1", "2"})

    def test_deep_scan(self):
        data = {"a": {"b": {"c": 42}}}
        result = JsonPathEngine.query(data, "$..c")
        self.assertEqual(result, ["42"])

    def test_bracket_key(self):
        data = {"complex key": "value"}
        result = JsonPathEngine.query(data, "$['complex key']")
        self.assertEqual(result, ["value"])

    def test_query_first(self):
        result = JsonPathEngine.query_first(JSON_BOOK_LIST, "$.total")
        self.assertEqual(result, "2")

    def test_nonexistent(self):
        result = JsonPathEngine.query_first(JSON_BOOK_LIST, "$.nonexistent")
        self.assertIsNone(result)


# ═════════════════════════════════════════════════════════════════
# Legado 选择器测试 (移植自 talebook fork)
# ═════════════════════════════════════════════════════════════════

class TestLegadoSelector(unittest.TestCase):
    def test_class_shorthand(self):
        nodes, attr = legado_select(HTML_LEGADO, "class.bookname@a@text")
        self.assertGreater(len(nodes), 0)
        self.assertIn("测试书名", nodes[0].get_text())

    def test_extract_one_text(self):
        result = legado_extract_one("class.bookname@a@text", HTML_LEGADO)
        self.assertEqual(result, "测试书名")

    def test_extract_one_href(self):
        result = legado_extract_one("class.bookname@a@href", HTML_LEGADO, base_url="https://www.deqixs.com")
        self.assertEqual(result, "https://www.deqixs.com/book/1")

    def test_extract_list(self):
        item_rules = {
            "name": "class.bookname@a@text",
            "author": "class.author@text",
        }
        results = legado_extract_list("class.bookcase@li", item_rules, HTML_LEGADO)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "测试书名")
        self.assertEqual(results[1]["author"], "测试作者2")

    def test_index_syntax_dot(self):
        """测试 .0 / .1 索引语法"""
        nodes, attr = legado_select(HTML_LEGADO, "class.bookcase@li.0@class.bookname@a@text")
        self.assertGreater(len(nodes), 0)

    def test_tail_regex(self):
        """测试 ## 尾部正则（替换模式）"""
        html = '<div class="test">abc123def</div>'
        # ##\d+ with empty replacement → removes digits
        result = legado_extract_one("class.test@text##\\d+", html)
        self.assertEqual(result, "abcdef")

    def test_tail_regex_replace(self):
        html = '<a href="/book/123">title</a>'
        result = legado_extract_one("a@href##/book/(\\d+)##$1", html)
        self.assertEqual(result, "123")

    def test_owntext_attr(self):
        html = '<div class="x">prefix<span>ignore</span>suffix</div>'
        result = legado_extract_one("class.x@owntext", html)
        self.assertIn("prefix", result or "")
        self.assertIn("suffix", result or "")

    def test_textnodes_attr(self):
        html = '<div class="x">a<br>b</div>'
        result = legado_extract_one("class.x@textnodes", html)
        self.assertIn("a", result or "")
        self.assertIn("b", result or "")

    def test_nested_element_extract(self):
        """从 Tag 元素中提取"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(HTML_LEGADO, "html.parser")
        container = soup.select_one(".bookcase li")
        result = legado_extract_from_element(container, "class.bookname@a@text")
        self.assertEqual(result, "测试书名")

    def test_empty_rule(self):
        result = legado_extract_one("", HTML_LEGADO)
        # Empty rule returns full text of the document
        self.assertIsNotNone(result)
        self.assertIn("测试书名", result or "")

    def test_legado_shorthand_tag(self):
        html = "<div><span class='x'>hello</span></div>"
        nodes, attr = legado_select(html, "tag.span")
        self.assertEqual(len(nodes), 1)

    def test_legado_shorthand_id(self):
        html = "<div><span id='x'>hello</span></div>"
        nodes, attr = legado_select(html, "id.x")
        self.assertEqual(len(nodes), 1)

    def test_legado_shorthand_text(self):
        html = "<div><span>hello world</span><p>other</p></div>"
        nodes, attr = legado_select(html, "text.hello")
        self.assertEqual(len(nodes), 1)


# ═════════════════════════════════════════════════════════════════
# Header / searchUrl 解析测试
# ═════════════════════════════════════════════════════════════════

class TestHeaderSearchUrl(unittest.TestCase):
    def test_header_dict(self):
        result = parse_source_header({"User-Agent": "test"})
        self.assertEqual(result, {"User-Agent": "test"})

    def test_header_json_string(self):
        result = parse_source_header('{"User-Agent": "test", "Referer": "https://x.com"}')
        self.assertEqual(result.get("User-Agent"), "test")
        self.assertEqual(result.get("Referer"), "https://x.com")

    def test_header_empty(self):
        self.assertEqual(parse_source_header(None), {})
        self.assertEqual(parse_source_header({}), {})
        self.assertEqual(parse_source_header(""), {})

    def test_header_js_returns_empty(self):
        """@js: 开头的 header 不能被解析，返回空"""
        self.assertEqual(parse_source_header("@js:({})"), {})

    def test_header_invalid_json(self):
        self.assertEqual(parse_source_header("not json"), {})

    def test_parse_search_url_simple(self):
        url, opts = _parse_search_url("https://example.com/search?q={{key}}")
        self.assertEqual(url, "https://example.com/search?q={{key}}")
        self.assertEqual(opts, {})

    def test_parse_search_url_with_opts(self):
        raw = 'https://example.com/search,{"method":"POST","body":"key={{key}}","charset":"gbk"}'
        url, opts = _parse_search_url(raw)
        self.assertEqual(url, "https://example.com/search")
        self.assertEqual(opts.get("method"), "POST")
        self.assertEqual(opts.get("body"), "key={{key}}")
        self.assertEqual(opts.get("charset"), "gbk")

    def test_parse_search_url_invalid_json_after_comma(self):
        url, opts = _parse_search_url("https://example.com,{invalid}")
        self.assertEqual(url, "https://example.com,{invalid}")


# ═════════════════════════════════════════════════════════════════
# URL 模板引擎测试
# ═════════════════════════════════════════════════════════════════

class TestUrlTemplate(unittest.TestCase):
    def test_key_replacement(self):
        result = render_url_template("https://example.com/search?q={{key}}", key="测试")
        self.assertIn("q=%E6%B5%8B%E8%AF%95", result)

    def test_page_replacement(self):
        result = render_url_template("https://example.com/page/{{page}}", page=3)
        self.assertEqual(result, "https://example.com/page/3")

    def test_no_template(self):
        result = render_url_template("https://example.com/static")
        self.assertEqual(result, "https://example.com/static")


# ═════════════════════════════════════════════════════════════════
# 统一入口 extract_single / extract_list 测试
# ═════════════════════════════════════════════════════════════════

class TestExtractSingle(unittest.TestCase):
    def test_css_rule(self):
        result = extract_single("h3.title@text", HTML_BOOK_LIST)
        self.assertEqual(result, "书名A")

    def test_html_attr(self):
        result = extract_single("h3.title a@href", HTML_BOOK_LIST)
        self.assertEqual(result, "/book/1")

    def test_empty_rule(self):
        self.assertIsNone(extract_single("", HTML_BOOK_LIST))

    def test_legado_rule(self):
        result = extract_single("class.bookname@a@text", HTML_LEGADO)
        self.assertEqual(result, "测试书名")

    def test_regex_rule(self):
        result = extract_single("/书名(.)/", HTML_BOOK_LIST)
        self.assertEqual(result, "A")

    def test_and_concat(self):
        """&& 组合符直接拼接，无分隔符"""
        result = extract_single("h3.title@text&&p.author@text", HTML_BOOK_LIST)
        self.assertEqual(result, "书名A作者A")

    def test_jsonpath_rule(self):
        result = extract_single("$.total", json.dumps(JSON_BOOK_LIST))
        self.assertEqual(result, "2")


class TestExtractList(unittest.TestCase):
    def test_css_list(self):
        rules = {"name": "h3.title@text", "author": "p.author@text"}
        results = extract_list("ul.book-list li", rules, HTML_BOOK_LIST)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "书名A")
        self.assertEqual(results[1]["author"], "作者B")

    def test_legado_list(self):
        rules = {"name": "class.bookname@a@text", "author": "class.author@text"}
        results = extract_list("class.bookcase@li", rules, HTML_LEGADO)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "测试书名")
        self.assertEqual(results[1]["author"], "测试作者2")


# ═════════════════════════════════════════════════════════════════
# 内容净化 (replaceRegex) 测试
# ═════════════════════════════════════════════════════════════════

class TestReplaceRegex(unittest.TestCase):
    def test_simple_replace(self):
        rules = [{"pattern": "foo", "replacement": "bar", "isRegex": False}]
        result = apply_replace_rules("foo hello", rules)
        self.assertEqual(result, "bar hello")

    def test_regex_replace(self):
        rules = [{"pattern": r"\d+", "replacement": "N", "isRegex": True}]
        result = apply_replace_rules("abc123def456", rules)
        self.assertEqual(result, "abcNdefN")

    def test_multiple_rules(self):
        rules = [
            {"pattern": "a", "replacement": "x", "isRegex": False},
            {"pattern": "b", "replacement": "y", "isRegex": False},
        ]
        result = apply_replace_rules("ab", rules)
        self.assertEqual(result, "xy")

    def test_rule_object(self):
        from book_source_model import ReplaceRule
        rules = [ReplaceRule(pattern="old", replacement="new", isRegex=False)]
        result = apply_replace_rules("old text", rules)
        self.assertEqual(result, "new text")


# ═════════════════════════════════════════════════════════════════
# 模型测试
# ═════════════════════════════════════════════════════════════════

class TestBookSourceModel(unittest.TestCase):
    def test_create_source(self):
        s = BookSource(
            bookSourceName="测试源",
            bookSourceUrl="https://example.com",
            bookSourceGroup="测试",
        )
        self.assertEqual(s.bookSourceName, "测试源")
        self.assertTrue(s.enabled)

    def test_to_dict(self):
        s = BookSource(bookSourceName="测试")
        d = s.to_dict()
        self.assertEqual(d["bookSourceName"], "测试")
        self.assertIn("ruleSearch", d)
        self.assertIn("ruleBookInfo", d)

    def test_from_dict(self):
        d = {
            "bookSourceName": "测试",
            "bookSourceUrl": "https://example.com",
            "ruleSearch": {"bookList": "ul.books>li", "name": "h3"},
        }
        s = BookSource.from_dict(d)
        self.assertEqual(s.bookSourceName, "测试")
        self.assertEqual(s.ruleSearch.bookList, "ul.books>li")

    def test_from_dict_extra_fields_ignored(self):
        """未知字段不报错"""
        d = {"bookSourceName": "测试", "unknown_field": "value"}
        s = BookSource.from_dict(d)
        self.assertEqual(s.bookSourceName, "测试")

    def test_to_json(self):
        s = BookSource(bookSourceName="测试")
        j = json.loads(s.to_json())
        self.assertEqual(j["bookSourceName"], "测试")

    def test_from_json(self):
        j = '{"bookSourceName": "测试JSON"}'
        s = BookSource.from_json(j)
        self.assertEqual(s.bookSourceName, "测试JSON")

    def test_load_dump_sources(self):
        sources = [BookSource(bookSourceName="源1"), BookSource(bookSourceName="源2")]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps([s.to_dict() for s in sources], ensure_ascii=False))
            f.flush()
            loaded = load_sources_from_json(f.name)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].bookSourceName, "源1")
            self.assertEqual(loaded[1].bookSourceName, "源2")

    def test_rule_content_replace_regex_from_dict(self):
        d = {
            "content": "id.content@html",
            "replaceRegex": [
                {"pattern": "old", "replacement": "new", "isRegex": False},
            ],
        }
        rc = RuleContent(**{k: v for k, v in d.items() if k in RuleContent.__dataclass_fields__})
        rc.replaceRegex = []
        from book_source_model import _content_from_dict
        rc2 = _content_from_dict(d)
        self.assertEqual(len(rc2.replaceRegex), 1)
        self.assertEqual(rc2.replaceRegex[0].pattern, "old")


# ═════════════════════════════════════════════════════════════════
# JS 运行时测试
# ═════════════════════════════════════════════════════════════════

class TestJsRuntime(unittest.TestCase):
    def test_simple_replace(self):
        result = run_js("result.replace('foo', 'bar')", result="foo hello")
        self.assertEqual(result, "bar hello")

    def test_string_operation(self):
        result = run_js("result.trim().toUpperCase()", result="  hello  ")
        self.assertEqual(result, "HELLO")

    def test_arithmetic(self):
        result = run_js("String(parseInt(result) * 2)", result="21")
        self.assertEqual(result, "42")

    def test_java_ajax_raises(self):
        with self.assertRaises(JsRuleUnsupported):
            run_js("java.ajax('url')")

    def test_java_getString_raises(self):
        with self.assertRaises(JsRuleUnsupported):
            run_js("java.getString()")

    def test_js_lib_functions(self):
        js_lib = "function double(x) { return String(parseInt(x) * 2); }"
        result = run_js("double(result)", result="21", js_lib=js_lib)
        self.assertEqual(result, "42")

    def test_empty_code(self):
        result = run_js("", result="保持不变")
        self.assertEqual(result, "保持不变")

    def test_boolean_result(self):
        result = run_js("result === 'yes'", result="yes")
        self.assertEqual(result, "true")


# ═════════════════════════════════════════════════════════════════
# Legado + JS 集成测试
# ═════════════════════════════════════════════════════════════════

class TestLegadoWithJs(unittest.TestCase):
    def test_legado_rule_with_js_tail(self):
        """@js: 在规则尾部"""
        rule = "class.bookname@a@text@js:result.replace('测试', '正式')"
        result = legado_extract_one(rule, HTML_LEGADO)
        self.assertEqual(result, "正式书名")

    def test_legado_rule_js_with_lib(self):
        """使用 jsLib 中的 cover() 函数"""
        js_lib = "function cover(url) { return 'https://www.example.com' + url; }"
        rule = "class.bookcover@img@src@js:cover(result)"
        result = legado_extract_one(rule, HTML_LEGADO, js_lib=js_lib)
        self.assertEqual(result, "https://www.example.com/cover/1.jpg")

    def test_legado_rule_js_words(self):
        """使用 jsLib 中的 words() 函数提取数字"""
        js_lib = "function words(str) { var m = str.match(/\\d+/); return m ? m[0] : str; }"
        html = '<div id="status"><span>字数：1234567</span></div>'
        rule = "id.status@span@text##字数：||@js:words(result)"
        result = legado_extract_one(rule, html, js_lib=js_lib)
        self.assertEqual(result, "1234567")

    def test_legado_rule_js_unsupported_fallback(self):
        """java.ajax 在 Legado 规则中 JS 失败时返回原始提取值"""
        rule = "class.bookname@a@href@js:java.ajax(result)"
        result = legado_extract_one(rule, HTML_LEGADO)
        # JS 执行失败返回提取到的原始值，而不是 None
        self.assertEqual(result, "/book/1")


# ═════════════════════════════════════════════════════════════════
# 工具函数测试
# ═════════════════════════════════════════════════════════════════

class TestUtils(unittest.TestCase):
    def test_is_json_content(self):
        self.assertTrue(is_json_content('{"key": "value"}'))
        self.assertTrue(is_json_content('[1, 2, 3]'))
        self.assertFalse(is_json_content('<html></html>'))
        self.assertFalse(is_json_content(''))

    def test_guess_response_type(self):
        self.assertEqual(guess_response_type('{"key": "value"}'), "json")
        self.assertEqual(guess_response_type('<html></html>'), "html")

    def test_lxml_html_parsing(self):
        """确认 lxml HTML parser 能正常解析 Unicode 字符串"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup("<p>test</p>", "lxml")
        self.assertIsNotNone(soup)
        self.assertIn("test", soup.get_text())


# ═════════════════════════════════════════════════════════════════
# 内容净化 + Edge cases
# ═════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    def test_html_with_xml_declaration(self):
        """lxml 处理包含 XML 声明的 Unicode 字符串"""
        from bs4 import BeautifulSoup
        html = '<?xml version="1.0" encoding="utf-8"?><html><body><p>内容</p></body></html>'
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text()
        self.assertIn("内容", text)

    def test_content_fallback_import(self):
        """确认 content_fallbacks 模块可导入"""
        try:
            from content_fallbacks import fetch_content, register, find_handler
            self.assertTrue(callable(fetch_content))
            self.assertTrue(callable(register))
            self.assertTrue(callable(find_handler))
        except ImportError as e:
            self.fail(f"content_fallbacks 导入失败: {e}")

    def test_epub_helper_import(self):
        """确认 epub_helper 模块可导入"""
        try:
            from epub_helper import generate_epub, _clean_html_for_epub
            self.assertTrue(callable(generate_epub))
            self.assertTrue(callable(_clean_html_for_epub))
        except ImportError as e:
            self.fail(f"epub_helper 导入失败: {e}")

    def test_clean_html_for_epub(self):
        from epub_helper import _clean_html_for_epub
        result = _clean_html_for_epub('<p>hello world</p>')
        self.assertIn("hello world", result)

    def test_clean_html_with_xml_decl(self):
        from epub_helper import _clean_html_for_epub
        html = '<?xml version="1.0" encoding="utf-8"?><p>内容</p>'
        result = _clean_html_for_epub(html)
        self.assertNotIn("<?xml", result)
        self.assertIn("内容", result)


# ═════════════════════════════════════════════════════════════════
# 完整流程测试（带 mock）
# ═════════════════════════════════════════════════════════════════

class MockResp:
    """模拟 requests.Response。"""
    status_code = 200
    apparent_encoding = "utf-8"
    encoding = ""

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class MockSession:
    """模拟 requests.Session，所有请求返回固定文本。"""
    headers = {}

    def __init__(self, text):
        self._text = text

    def get(self, url, **kwargs):
        return MockResp(self._text)

    def post(self, url, **kwargs):
        return MockResp(self._text)


class TestFullFlow(unittest.TestCase):
    def setUp(self):
        self.source = BookSource(
            bookSourceName="测试源",
            bookSourceUrl="https://example.com",
            ruleSearch=RuleSearch(
                bookList="ul.book-list li",
                name="h3.title@text",
                author="p.author@text",
                coverUrl="img.cover@src",
                bookUrl="h3.title a@href",
            ),
            ruleBookInfo=RuleBookInfo(
                name="h1.bookname@text",
                author="p.author a@text",
                lastChapter="p.chapter a@text",
                intro="div.intro@text",
                coverUrl="img.bookcover@src",
                wordCount="",
            ),
            ruleToc=RuleToc(
                chapterList="#list dd a",
                chapterName="@text",
                chapterUrl="@href",
            ),
            ruleContent=RuleContent(
                content="#content@html",
            ),
        )

    def _mock_session(self, text):
        """构造返回固定 HTML 的 mock session，patch build_source_session。"""
        from unittest.mock import patch
        return patch("rule_engine.build_source_session", return_value=MockSession(text))

    def test_search_books_css(self):
        """测试基于 CSS 的搜索"""
        with self._mock_session(HTML_BOOK_LIST):
            results = search_books(self.source, "test")
            self.assertGreater(len(results), 0)
            if results:
                self.assertIn("书名A", results[0].get("name", ""))

    def test_fetch_book_info(self):
        """测试书籍详情抓取"""
        with self._mock_session(HTML_DETAIL):
            detail = fetch_book_info(self.source, "/book/1")
            self.assertEqual(detail.get("name"), "书名A")
            self.assertEqual(detail.get("author"), "作者A")
            self.assertIn("简介", detail.get("intro", ""))

    def test_fetch_toc(self):
        """测试目录抓取"""
        with self._mock_session(HTML_TOC):
            toc = fetch_toc(self.source, "/book/1")
            self.assertEqual(len(toc), 3)
            if toc:
                self.assertEqual(toc[0].get("chapterName"), "第一章 开始")

    def test_fetch_content(self):
        """测试正文抓取"""
        with self._mock_session(HTML_CONTENT):
            content = fetch_content(self.source, "/c/1")
            self.assertIsNotNone(content)
            if content:
                self.assertIn("正文第一段", content)

    def test_fetch_content_with_source_regex(self):
        """sourceRegex 先从页面源码截取正文片段"""
        source = self.source
        source.ruleContent = RuleContent(
            content="p@text",
            sourceRegex=r'<div id="content">([\s\S]*?)</div>',
        )
        with self._mock_session(HTML_CONTENT):
            content = fetch_content(source, "/c/1")
            self.assertIn("正文第一段", content)

    def test_fetch_toc_is_volume_flag(self):
        """卷头行 isVolume 规则正确标记"""
        html = (
            '<div id="list"><dl>'
            '<dd><span class="vol">第一卷</span><a href="/v/1">第一卷</a></dd>'
            '<dd><a href="/c/1">第一章</a></dd>'
            '</dl></div>'
        )
        source = self.source
        source.ruleToc = RuleToc(
            chapterList="#list dd",
            chapterName="a@text",
            chapterUrl="a@href",
            isVolume="class.vol@text",
        )
        with self._mock_session(html):
            toc = fetch_toc(source, "/book/1")
            self.assertEqual(len(toc), 2)
            self.assertEqual(toc[0].get("isVolume"), "第一卷")
            self.assertEqual(toc[1].get("isVolume"), "")


# ═════════════════════════════════════════════════════════════════
# deqixs_test.json 验证测试
# ═════════════════════════════════════════════════════════════════

class TestDeqixsSource(unittest.TestCase):
    def test_load_deqixs_json(self):
        path = os.path.join(os.path.dirname(__file__), "deqixs_test.json")
        self.assertTrue(os.path.exists(path))
        sources = load_sources_from_json(path)
        self.assertEqual(len(sources), 1)
        s = sources[0]
        self.assertEqual(s.bookSourceName, "得奇小说")
        self.assertIn("searchUrl", s.to_dict())
        self.assertIn("jsLib", s.to_dict())
        self.assertTrue(s.searchUrl.startswith("https://"))
        self.assertTrue(s.ruleToc.chapterList.startswith("id."))
        self.assertTrue(s.ruleContent.content.startswith("id."))


# ═════════════════════════════════════════════════════════════════
# 入口
# ═════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
