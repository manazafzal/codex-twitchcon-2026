"""The packaged vocabulary policy stores digests, keeping prohibited text out of assets."""

import hashlib
import json
import re
from importlib.resources import files


def prohibited(text: str) -> bool:
    tokens = re.findall(r"[\w']+", text.casefold().replace("\u2019", "'"))
    rules = json.loads(files("nous.concepts").joinpath("name_policy.json").read_text())
    for rule in rules:
        for start in range(len(tokens) - len(rule) + 1):
            if all(
                hashlib.sha256(token[: word["length"]].encode()).hexdigest() == word["sha256"]
                for token, word in zip(tokens[start:], rule, strict=False)
            ):
                return True
    return False


def validate_name(name: str, *, chat: bool = False) -> str:
    pattern = r"[A-Za-z]{3,20}" if chat else r"[A-Za-z][A-Za-z -]{1,38}[A-Za-z]"
    if not re.fullmatch(pattern, name) or prohibited(name):
        raise ValueError("Please choose a short topic using ordinary letters.")
    return "-".join(name.casefold().split())
