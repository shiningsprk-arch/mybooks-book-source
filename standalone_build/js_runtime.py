"""
js_runtime 鈥?鍙楅檺鐨勪功婧?JS 杩愯鏃躲€?
鍩轰簬 dukpy (Duktape) 寮曟搸锛屽彧鏀寔绠€鍗曞瓧娈靛悗澶勭悊锛?  - result.replace(...)
  - 鐢ㄦ埛鑷畾涔夊嚱鏁帮紙閫氳繃 jsLib 瀛楁娉ㄥ唽锛?  - String 鎿嶄綔

涓嶆敮鎸?java.ajax / java.getString / <js> 鍧楃瓑澶栭儴鍓綔鐢ㄦ搷浣溿€?"""
import base64 as _b64
import hashlib as _hl
import json
import logging
import re
import threading
from collections import OrderedDict
from urllib.parse import urlparse

try:
    import dukpy
    _HAS_DUKPY = True
except Exception:  # pragma: no cover - dukpy 鏃犲搴斿钩鍙?wheel 鏃堕檷绾?    dukpy = None
    _HAS_DUKPY = False

logger = logging.getLogger(__name__)

_interp_cache: "OrderedDict[str, dukpy.JSInterpreter]" = OrderedDict()
_interp_cache_lock = threading.Lock()
_INTERP_CACHE_MAX = 32
_MAX_JS_LEN = 50000

# 甯歌鏃犵晫寰幆妯″紡锛堟棤娉曡鎵撴柇锛岀洿鎺ユ嫆缁濇墽琛岋級
_RE_UNBOUNDED_LOOP = re.compile(
    r"\bwhile\s*\(\s*(?:true|1|'1'|\"1\"|1\s*=\s*1)\s*\)"
    r"|\bfor\s*\(\s*;\s*;\s*\)"
    r"|\bwhile\s*\(\s*(?:true|1)\s*\)\s*\{\s*\}",
    re.IGNORECASE,
)


class JsRuleUnsupported(Exception):
    """JS 瑙勫垯涓嶅彈鏀寔锛堝惈 java.ajax 绛夊閮ㄥ壇浣滅敤锛夈€?""


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
    lines.append(r"""
var __javaStore = {};
var java = {
    get: function(key) { return __javaStore[key] || ""; },
    put: function(key, value) { __javaStore[key] = String(value); return value; },
    md5Encode: function(str) {
        var hash = dukpy_md5(String(str));
        return hash;
    },
    base64Encode: function(str) {
        var b = dukpy_b64(String(str));
        return b;
    },
    log: function(msg) { dukpy_log(String(msg)); return ""; },
    longToast: function() { return ""; },
    t2s: function(value) { return value == null ? "" : String(value); },
    s2t: function(value) { return value == null ? "" : String(value); },
    encodeURI: function(value) { return encodeURIComponent(String(value)); },
    getString: function() { throw new Error("java.getString not supported"); },
    ajax: function() { throw new Error("java.ajax not supported"); },
    post: function() { throw new Error("java.post not supported"); },
};
var book = Object.freeze({
    origin: __origin,
    name: "",
    author: ""
});
""")
    return "\n".join(lines)

def _dukpy_md5(s):
    return _hl.md5(s.encode()).hexdigest()

def _dukpy_b64(s):
    return _b64.b64encode(s.encode()).decode()

def _dukpy_log(msg):
    logger.info("[JS] %s", msg)


def _get_interp(js_lib: str = "") -> dukpy.JSInterpreter:
    """鎸?jsLib 鍐呭缂撳瓨瑙ｉ噴鍣紝LRU 涓婇檺 _INTERP_CACHE_MAX銆?""
    if not _HAS_DUKPY:
        raise JsRuleUnsupported("dukpy 鏈畨瑁咃紝鏃犳硶鎵ц JS 瑙勫垯")
    cache_key = js_lib or "__default__"
    with _interp_cache_lock:
        interp = _interp_cache.get(cache_key)
        if interp is not None:
            _interp_cache.move_to_end(cache_key)
            return interp
    interp = dukpy.JSInterpreter()
    if js_lib:
        try:
            interp.evaljs(js_lib)
        except Exception as exc:
            logger.warning("jsLib 鍔犺浇澶辫触: %s", exc)
    with _interp_cache_lock:
        _interp_cache[cache_key] = interp
        while len(_interp_cache) > _INTERP_CACHE_MAX:
            _interp_cache.popitem(last=False)
    return interp


def _detect_unsafe_js(code: str) -> bool:
    low = code.lower()
    unsafe_markers = [
        "java.ajax", "java.post", "java.getstring",
        "java.startbrowserawait", "java.getstring",
    ]
    if any(m in low for m in unsafe_markers):
        return True
    if _RE_UNBOUNDED_LOOP.search(code):
        return True
    return False


def run_js(code: str, result: str = "", variables: dict = None,
           base_url: str = "", js_lib: str = "") -> str:
    """鎵ц涓€鏉?@js: 瑙勫垯浠ｇ爜銆?""
    code = (code or "").strip()
    if not code:
        return result

    if len(code) > _MAX_JS_LEN:
        raise JsRuleUnsupported(f"JS rule too long ({len(code)} > {_MAX_JS_LEN})")

    if _detect_unsafe_js(code):
        raise JsRuleUnsupported(code)

    globals_code = _build_globals_code(variables or {}, result, base_url)
    full_js = f"{globals_code}\n{code}"

    interp = _get_interp(js_lib)

    # Register native callback functions
    try:
        interp.export_function("dukpy_md5", _dukpy_md5)
        interp.export_function("dukpy_b64", _dukpy_b64)
        interp.export_function("dukpy_log", _dukpy_log)
    except Exception:
        pass

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
        logger.warning("JS 鎵ц澶辫触: %s 鈥?%s", code[:60], err_msg)
        raise JsRuleUnsupported(code) from exc

