import re
from dataclasses import dataclass

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
