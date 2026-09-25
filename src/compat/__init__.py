from .css import adapt_css
from .html import adapt_html
from .js import adapt_js, analyze_js
from .target import LegacyTarget, detect_target, unsupported_js_features

__all__ = ["LegacyTarget", "adapt_css", "adapt_html", "adapt_js", "analyze_js", "detect_target", "unsupported_js_features"]
