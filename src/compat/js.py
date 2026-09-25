import hashlib
import json
import re
import subprocess
from pathlib import Path
from .target import unsupported_js_features

_FEATURE_PATTERNS = {
    "let": r"\blet\b",
    "const": r"\bconst\b",
    "arrow-functions": r"=>",
    "class": r"\bclass\b",
    "template-literals": r"`",
    "async": r"\basync\b",
    "await": r"\bawait\b",
    "optional-chaining": r"\?\.",
    "nullish-coalescing": r"\?\?",
    "promise": r"\bPromise\b",
    "fetch": r"\bfetch\s*\(",
    "object-assign": r"\bObject\s*\.\s*assign\s*\(",
    "array-from": r"\bArray\s*\.\s*from\s*\(",
    "symbol": r"\bSymbol\b",
    "map": r"\bMap\b",
    "set": r"\bSet\b",
    "weakmap": r"\bWeakMap\b",
    "weakset": r"\bWeakSet\b",
    "url": r"\bURL\s*\(",
    "url-search-params": r"\bURLSearchParams\b",
    "object-entries": r"\bObject\s*\.\s*entries\s*\(",
    "object-values": r"\bObject\s*\.\s*values\s*\(",
    "object-from-entries": r"\bObject\s*\.\s*fromEntries\s*\(",
    "array-includes": r"(?:\[[^\]]*\]|\b(?:arr|array|arrays|items|list|values|elements)\b)\s*\.\s*includes\s*\(",
    "string-includes": r"(?:[\"\'][^\"\']*[\"\']|\b(?:str|string|text|name|title|message|value|url)\b)\s*\.\s*includes\s*\(",
    "string-starts-with": r"\.\s*startsWith\s*\(",
    "string-ends-with": r"\.\s*endsWith\s*\(",
    "element-closest": r"\.\s*closest\s*\(",
    "element-matches": r"\.\s*matches\s*\(",
    "custom-event": r"\bCustomEvent\b",
    "intersection-observer": r"\bIntersectionObserver\b",
    "mutation-observer": r"\bMutationObserver\b",
}
RUNTIME_FEATURES = {
    "promise", "fetch", "object-assign", "array-from", "symbol", "map", "set",
    "weakmap", "weakset", "url", "url-search-params", "object-entries",
    "object-values", "object-from-entries", "array-includes", "string-includes",
    "string-starts-with", "string-ends-with", "element-closest", "element-matches",
    "custom-event", "intersection-observer", "mutation-observer",
}
_SYNTAX_FEATURES = {
    "let", "const", "arrow-functions", "class", "template-literals",
    "async", "await", "optional-chaining", "nullish-coalescing",
}
_JS_CACHE = {}

def analyze_js(source):
    features = set()
    for feature, pattern in _FEATURE_PATTERNS.items():
        if re.search(pattern, source):
            features.add(feature)
    return features

def adapt_js(source,target=None):
    if target is None or target.ios_major is None:
        return source

    unsupported = unsupported_js_features(target,analyze_js(source))
    if not unsupported & _SYNTAX_FEATURES:
        return source

    cache_key = (
        target.ios_major,
        hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )
    if cache_key in _JS_CACHE:
        print(f"[COMPAT] JS cache hit target=iOS {target.ios_major}")
        return _JS_CACHE[cache_key]

    helper = Path(__file__).resolve().parents[2]/"tools"/"transpile_js.mjs"
    try:
        result = subprocess.run(
            ["node",str(helper)],
            input=json.dumps({"source": source,"ios_major": target.ios_major}),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise RuntimeError(detail)
        output = json.loads(result.stdout)
        code = output.get("code")
        if not isinstance(code,str):
            raise RuntimeError("Babel returned no code")
        _JS_CACHE[cache_key] = code
        return code
    except Exception as error:
        print(f"[WARN] JS transpilation failed: {error}")
        return source
