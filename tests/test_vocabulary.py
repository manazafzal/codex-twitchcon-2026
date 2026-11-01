import ast
import re
from pathlib import Path

from thoughtquake.cli import main

ROOT = Path(__file__).resolve().parents[1]


def forbidden_patterns():
    rules = (ROOT / "AGENTS.md").read_text().split("1. **Vocabulary.**", 1)[1].split("\n2.", 1)[0]
    prohibited = rules.split("Do NOT use:", 1)[1]
    return [
        re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
        for term in re.findall(r'"([^"]+)"', prohibited)
    ]


def python_strings(path):
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                docstrings.add(id(value))
    return "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    )


def violations(text):
    return [p.pattern for p in forbidden_patterns() if p.search(text)]


def test_user_facing_files():
    paths = [ROOT / "README.md"]
    paths += list((ROOT / "docs").rglob("*"))
    paths += list((ROOT / "src").rglob("*"))
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
    assert violations("STEERING")
    assert violations("activation steering")
    assert not violations("a cheerful daily task")


def test_overlay_keeps_simulated_badge_logic():
    script = (ROOT / "src/thoughtquake/overlay/app.js").read_text()
    assert "SIMULATED ×" in script
    assert "handlers.badge" in script
    assert "event.label" in script
