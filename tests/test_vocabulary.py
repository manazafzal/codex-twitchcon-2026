import ast
import re
from pathlib import Path

from nous.cli import main

ROOT = Path(__file__).resolve().parents[1]


def forbidden_patterns():
    rules = (ROOT / "AGENTS.md").read_text().split("1. **Vocabulary.**", 1)[1].split("\n2.", 1)[0]
    prohibited = rules.split("Do NOT use:", 1)[1]
    patterns = []
    for term in re.findall(r'"([^"]+)"', prohibited):
        words = []
        for word in term.casefold().split():
            for suffix in ("ing", "ion", "ed"):
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    word = word[: -len(suffix)]
                    break
            if len(word) > 4 and word.endswith("e"):
                word = word[:-1]
            words.append(re.escape(word) + r"\w*")
        patterns.append(re.compile(r"(?<!\w)" + r"\s+".join(words), re.IGNORECASE))
    return patterns


def python_strings(path):
    tree = ast.parse(path.read_text())
    return "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def violations(text):
    return [p.pattern for p in forbidden_patterns() if p.search(text.replace("\u2019", "'"))]


def test_user_facing_files():
    paths = [ROOT / "README.md"]
    paths += list((ROOT / "docs").rglob("*"))
    paths += list((ROOT / "src").rglob("*"))
    paths += list((ROOT / "tests").rglob("*"))
    paths += list((ROOT / ".codex/skills").rglob("*"))
    for path in paths:
        if not path.is_file() or path == ROOT / "docs/related-work.md":
            continue
        if path.suffix not in {".md", ".py", ".html", ".css", ".js", ".yaml"}:
            continue
        text = python_strings(path) if path.suffix == ".py" else path.read_text()
        assert not violations(text), f"{path}: {violations(text)}"


def test_cli_help(capsys):
    import pytest

    for args in [["--help"], ["demo", "--help"], ["build-library", "--help"], ["eval", "--help"]]:
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 0
        assert not violations(capsys.readouterr().out)


def test_detector_catches_case_and_word_boundaries():
    rules = (ROOT / "AGENTS.md").read_text().split("Do NOT use:", 1)[1]
    term = re.findall(r'"([^"]+)"', rules)[0]
    assert violations(term.upper())
    assert violations(term + "ed")
    assert not violations("a cheerful daily task")


def test_overlay_keeps_simulated_badge_logic():
    script = (ROOT / "src/nous/overlay/app.js").read_text()
    assert "SIMULATED ×" in script
    assert "handlers.badge" in script
    assert "event.label" in script
