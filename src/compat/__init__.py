from .css import adapt_css
from .html import adapt_html
from .js import RUNTIME_FEATURES, adapt_js, analyze_js
from .runtime import required_polyfills
from .target import LegacyTarget, detect_target, unsupported_js_features

__all__ = ["LegacyTarget", "RUNTIME_FEATURES", "adapt_css", "adapt_html", "adapt_js", "analyze_js", "detect_target", "required_polyfills", "unsupported_js_features"]
