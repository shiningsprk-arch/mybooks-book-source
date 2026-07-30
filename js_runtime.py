"""
js_runtime — 受限的书源 JS 运行时。

基于 dukpy (Duktape) 引擎，只支持简单字段后处理：
  - result.replace(...)
  - 用户自定义函数（通过 jsLib 字段注册）
  - String 操作

不支持 java.ajax / java.getString / <js> 块等外部副作用操作。
"""
import json
import logging
from urllib.parse import urlparse

import dukpy

logger = logging.getLogger(__name__)

_interp_cache: dict[str, dukpy.JSInterpreter] = {}


class JsRuleUnsupported(Exception):
    """JS 规则不受支持（含 java.ajax 等外部副作用）。"""


def _build_globals_code(variables: dict, result: str = "", base_url: str = "") -> str:
    lines = []
    lines.append(f'var result = {json.dumps(result, ensure_ascii=False)};')
    if base_url:
        lines.append(f'var baseUrl = {json.dumps(base_url, ensure_ascii=False)};')
    for k, v in variables.items():
        if k in ('result', 'baseUrl'):
            continue
        lines.append(f'var {k} = {json.dumps(v, ensure_ascii=False)};')
    origin = ""
    parsed = urlparse(base_url or "")
    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
    lines.append(f'var __origin = {json.dumps(origin, ensure_ascii=False)};')
    lines.append("""
var java = Object.freeze({
    get: function(key) { return ""; },
    put: function(key, value) { return value; },
    getString: function() { throw new Error("java.getString is not supported"); },
    ajax: function() { throw new Error("java.ajax is not supported"); },
    post: function() { throw new Error("java.post is not supported"); },
    longToast: function() { return ""; },
    log: function() { return ""; },
    t2s: function(value) { return value == null ? "" : String(value); },
    s2t: function(value) { return value == null ? "" : String(value); },
    encodeURI: function(value) { return encodeURIComponent(String(value)); }
});
var book = Object.freeze({
    origin: __origin,
    name: "",
    author: ""
});
""")
    return "\n".join(lines)


def _get_interp(js_lib: str = "") -> dukpy.JSInterpreter:
    cache_key = js_lib or "__default__"
    if cache_key not in _interp_cache:
        interp = dukpy.JSInterpreter()
        if js_lib:
            try:
                interp.evaljs(js_lib)
            except Exception as exc:
                logger.warning("jsLib 加载失败: %s", exc)
        _interp_cache[cache_key] = interp
    return _interp_cache[cache_key]


def _detect_unsafe_js(code: str) -> bool:
    low = code.lower()
    unsafe_markers = [
        "java.ajax", "java.post", "java.getstring",
        "java.startbrowserawait", "java.getstring",
    ]
    return any(m in low for m in unsafe_markers)


def run_js(code: str, result: str = "", variables: dict = None,
           base_url: str = "", js_lib: str = "") -> str:
    """执行一条 @js: 规则代码。"""
    code = (code or "").strip()
    if not code:
        return result

    if _detect_unsafe_js(code):
        raise JsRuleUnsupported(code)

    globals_code = _build_globals_code(variables or {}, result, base_url)
    full_js = f"{globals_code}\n{code}"

    interp = _get_interp(js_lib)

    try:
        value = interp.evaljs(full_js)
        if value is None:
            return result
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
    except Exception as exc:
        err_msg = str(exc)
        if "java." in err_msg:
            raise JsRuleUnsupported(code) from exc
        logger.warning("JS 执行失败: %s — %s", code[:60], err_msg)
        raise JsRuleUnsupported(code) from exc
