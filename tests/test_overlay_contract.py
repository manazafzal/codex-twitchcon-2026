import inspect
import re
from dataclasses import is_dataclass
from html.parser import HTMLParser
from importlib.resources import files

from nous.engine import events


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "script" and "src" in attrs:
            self.scripts.append(attrs["src"])


def test_every_event_has_an_overlay_handler():
    js = files("nous.overlay").joinpath("app.js").read_text()
    handlers = js.split("const handlers = {", 1)[1].split("function dispatch", 1)[0]
    for _, cls in inspect.getmembers(events, inspect.isclass):
        if is_dataclass(cls) and issubclass(cls, events.Event):
            kind = cls.__dataclass_fields__["kind"].default
            assert re.search(r"^    " + kind + r"(?:\(|,)", handlers, re.MULTILINE), kind


def test_pages_share_renderer_and_all_dom_targets_exist():
    overlay = files("nous.overlay")
    js = overlay.joinpath("app.js").read_text()
    for filename in ("index.html", "fixture.html"):
        page = Page()
        page.feed(overlay.joinpath(filename).read_text())
        assert len(page.ids) == len(set(page.ids))
        for target in re.findall(r'\$\("([\w-]+)"\)', js):
            assert target in page.ids, (filename, target)
        assert "app.js" in page.scripts
    assert "fixture.js" in js
    assert overlay.joinpath("index.html").read_text() == overlay.joinpath("fixture.html").read_text()
    assert "NOUS_FIXTURE" in overlay.joinpath("fixture.js").read_text()
    css = overlay.joinpath("style.css").read_text()
    assert "width: 1920px" in css and "height: 1080px" in css
    assert "120ms" in css and "600ms" in css
    assert "prefers-reduced-motion" in css
    assert "RECONNECTING" in overlay.joinpath("index.html").read_text()
    assert "innerHTML" not in js
