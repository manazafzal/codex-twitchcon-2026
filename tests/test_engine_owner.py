import ast
import asyncio
from pathlib import Path

from thoughtquake.engine.commands import SetMode
from thoughtquake.engine.events import Connection, Token
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.server.session import Session
from thoughtquake.sim.crowd import Crowd


def test_external_code_never_accesses_mixer_private_state():
    root = Path(__file__).parents[1] / "src/thoughtquake"
    for path in root.rglob("*.py"):
        if path.name == "mixer.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "_last",
                "_selected",
                "_beta",
                "_doses",
                "_history",
            }:
                assert False, f"{path}:{node.lineno}"


def test_queue_is_owner_and_failed_backend_recovers(monkeypatch, caplog):
    real_sleep = asyncio.sleep
    pauses = []

    async def sleep(delay):
        pauses.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    class Failing(MockBackend):
        def __init__(self):
            self.failures = 2

        def prefill(self, *args, **kwargs):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("private model contents")
            return super().prefill(*args, **kwargs)

    async def run():
        session = Session(backend=Failing(), crowd=Crowd(twitch_connected=True))
        session.switch_mode("attack")
        assert session.mode == "war"
        assert isinstance(session.pending.get_nowait(), SetMode)
        session.switch_mode("war")
        output = []
        stream = session.events()
        try:
            async for event in stream:
                output.append(event)
                if isinstance(event, Token):
                    break
        finally:
            await stream.aclose()
        assert any(isinstance(e, Connection) and e.state == "error" for e in output)
        assert any(isinstance(e, Connection) and e.state == "connected" for e in output)
        assert session.owner is None
        assert 0.5 in pauses and 1 in pauses

    asyncio.run(run())
    assert "private model contents" not in caplog.text


def test_second_owner_is_rejected():
    async def run():
        session = Session(crowd=Crowd(twitch_connected=True))
        stream = session.events()
        await anext(stream)
        duplicate = session.events()
        try:
            try:
                await anext(duplicate)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Second owner was allowed")
        finally:
            await duplicate.aclose()
            await stream.aclose()

    asyncio.run(run())
