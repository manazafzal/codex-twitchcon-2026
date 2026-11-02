"""Replace unusable generated replies without relaxing partition-integrity checks."""

import re
from collections.abc import Callable
from typing import TypeVar

from nous.concepts.probe import text_hash

T = TypeVar("T")
MAX_ATTEMPTS = 20
_REFUSAL = re.compile(
    r"^(?:(?:i(?:'m| am) sorry|sorry)[,!.\s]*(?:but\s+)?)?"
    r"(?:i (?:cannot|can't|can not)|i(?:'m| am) unable to)\s+"
    r"(?:assist|help|comply|provide|fulfil|fulfill)\b",
    re.IGNORECASE,
)


def usable(text: str, seen: set[str]) -> bool:
    normalized = " ".join(text.replace("\u2019", "'").split())
    return bool(normalized) and not _REFUSAL.match(normalized) and text_hash(text) not in seen


def replacement(generate: Callable[[int], tuple[str, T]], seen: set[str]) -> T:
    for attempt in range(MAX_ATTEMPTS):
        text, value = generate(attempt)
        if usable(text, seen):
            seen.add(text_hash(text))
            return value
    raise ValueError("Could not generate a distinct non-refusal reply after bounded retries")
