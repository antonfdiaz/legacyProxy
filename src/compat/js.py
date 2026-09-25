import re

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
}

def analyze_js(source):
    features = set()
    for feature, pattern in _FEATURE_PATTERNS.items():
        if re.search(pattern, source):
            features.add(feature)
    return features

def adapt_js(source,target=None):
    return source
