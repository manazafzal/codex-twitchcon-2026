"""Regenerate the packaged policy digests from the repository's authoritative rule."""

import hashlib
import json
import re
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    rule = (root / "AGENTS.md").read_text().split("1. **Vocabulary.**", 1)[1].split("\n2.", 1)[0]
    rows = []
    for term in re.findall(r'"([^"]+)"', rule.split("Do NOT use:", 1)[1]):
        row = []
        for word in term.casefold().split():
            for suffix in ("ing", "ion", "ed"):
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    word = word[: -len(suffix)]
                    break
            if len(word) > 4 and word.endswith("e"):
                word = word[:-1]
            row.append({"length": len(word), "sha256": hashlib.sha256(word.encode()).hexdigest()})
        rows.append(row)
    (root / "src/nous/concepts/name_policy.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
