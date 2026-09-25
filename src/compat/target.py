import re
from dataclasses import dataclass

@dataclass(frozen=True)
class LegacyTarget:
    name: str

def detect_target(user_agent):
    """Return the compatibility target represented by an iOS User-Agent."""
    if not isinstance(user_agent, str):
        return LegacyTarget("unknown")

    if not re.search(r"\b(?:iPhone|iPad|iPod|iOS)\b", user_agent, re.IGNORECASE):
        return LegacyTarget("unknown")

    match = re.search(
        r"(?:CPU (?:iPhone )?OS|iPhone OS|iOS)\s+(\d+)",
        user_agent,
        re.IGNORECASE,
    )
    if not match:
        return LegacyTarget("unknown")

    ios_major = int(match.group(1))
    if ios_major <= 4:
        name = "ios_3_4" if ios_major >= 3 else "unknown"
    elif ios_major <= 6:
        name = "ios_5_6"
    elif ios_major == 7:
        name = "ios_7"
    else:
        name = "ios_8_plus"

    return LegacyTarget(name)
