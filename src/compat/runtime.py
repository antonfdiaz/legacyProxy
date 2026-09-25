from .target import unsupported_js_features

POLYFILL_FEATURES = {
    "fetch", "object-entries", "object-values", "object-from-entries",
    "url-search-params",
}

def required_polyfills(target,features) -> set[str]:
    if target is None or target.ios_major is None:
        return set()
    return {
        feature for feature in features & POLYFILL_FEATURES
        if unsupported_js_features(target,{feature})
    }
