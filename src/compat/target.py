import re
from dataclasses import dataclass

MIN_IOS_SUPPORT = {
    "let": 10,
    "const": 10,
    "arrow-functions": 10,
    "class": 9,
    "template-literals": 9,
    "async": 11,
    "await": 11,
    "optional-chaining": 13,
    "nullish-coalescing": 13,
    "promise": 8,
    "fetch": 10, #10.3 only
    "object-assign": 8,
    "array-from": 9,
}

@dataclass(frozen=True)
class LegacyTarget:
    ios_major: int | None

def detect_target(user_agent):
    """Return the compatibility target represented by an iOS User-Agent."""
    if not isinstance(user_agent, str):
        return LegacyTarget(None)

    match = re.search(
        r"(?:CPU (?:iPhone )?OS|iPhone OS|iOS)\s+(\d+)",
        user_agent,
        re.IGNORECASE,
    )
    if not match:
        return LegacyTarget(None)

    return LegacyTarget(int(match.group(1)))

def unsupported_js_features(target,features) -> set[str]:
    if target is None or target.ios_major is None:
        return set()
    return {
        feature for feature in features
        if feature in MIN_IOS_SUPPORT
        and target.ios_major < MIN_IOS_SUPPORT[feature]
    }
