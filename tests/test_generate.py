import asyncio
import json

import numpy as np
import pytest

from thoughtquake.engine.events import Badge, Mode, Push, Tamper, Tick, Token
from thoughtquake.engine.generate import PROMPTS, Generator, readout_allowed
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.model.mock_backend import MockBackend


def test_events_and_determinism(library):
    def run():
        clock = FakeClock()
        engine = Generator(
            MockBackend(), library, Mixer(clock=clock), clock=clock, simulated_users=2, immune=True
        )
        engine.push(Push("sim_a", "ocean", 0, "SIMULATED"))
        engine.push(Push("sim_b", "space", 0, "SIMULATED"))
        events = list(engine.events(answers=4, max_tokens=24))
        assert len(engine.history) == 3
        return events

    events = run()
    assert [e.to_dict() for e in events] == [e.to_dict() for e in run()]
    assert isinstance(events[0], Badge)
    assert events[0].label == "SIMULATED ×2"
    assert sum(isinstance(e, Badge) for e in events) == 1
    assert sum(isinstance(e, Mode) for e in events) == 4
    assert sum(isinstance(e, Token) for e in events) == 96
    assert sum(isinstance(e, Tamper) for e in events) == 96
    assert any(isinstance(e, Push) for e in events)
    assert any(isinstance(e, Tick) for e in events)
    for event in events:
        data = json.loads(json.dumps(event.to_dict(), allow_nan=False))
        assert data["kind"] in {"badge", "push", "tick", "mode", "token", "tamper"}
        if isinstance(event, Token):
            assert set(data) == {"kind", "i", "text", "applied", "readout", "color"}
            assert set(data["readout"]) == {"scores", "top", "margin"}
            assert data["color"] == data["applied"]
            assert len(data["readout"]["scores"]) == 3
    assert len(PROMPTS) == len(set(PROMPTS)) == 40


def test_prefill_and_answer_schedule(library):
    class Recording(MockBackend):
        def __init__(self):
            self.injections = []

        def prefill(self, prompt, inject=None, defend=None, *, inject_prefill=False):
            self.injections.append((inject, inject_prefill))
            return super().prefill(prompt, inject, defend, inject_prefill=inject_prefill)

        def step(self, state, token, inject=None, defend=None):
            self.injections.append((inject, True))
            return super().step(state, token, inject, defend)

    clock = FakeClock()
    backend = Recording()
    engine = Generator(backend, library, Mixer(clock=clock), seed=3, clock=clock)
    engine.push(Push("a", "ocean", 0, "SIMULATED"))
    list(engine.events(max_tokens=5))
    assert len(backend.injections) == 6
    assert backend.injections[0][1]
    for vector, _ in backend.injections:
        np.testing.assert_array_equal(vector, backend.injections[0][0])


def test_colour_gate(tmp_path, library):
    with pytest.raises(ValueError, match="agreement"):
        Generator(MockBackend(), library, Mixer(), colour_source="readout")
    path = tmp_path / "eval.json"
    for source, score, expected in [
        ("TINY MODEL / CI", 1, False),
        ("realmodel", 0.74, False),
        ("realmodel", 0.75, True),
    ]:
        path.write_text(
            json.dumps(
                {"source": source, "schedule_modes": {"answer": {"window_agreement": score}}}
            )
        )
        assert readout_allowed(path, "answer") is expected
    Generator(MockBackend(), library, Mixer(), colour_source="readout", eval_path=path)
    assert not readout_allowed(path, "sentence")


def test_async_stream(library):
    async def run():
        engine = Generator(MockBackend(), library, Mixer())
        return [event async for event in engine.stream(max_tokens=3)]

    assert sum(isinstance(e, Token) for e in asyncio.run(run())) == 3


def test_stream_holds_previous_answer_and_uses_single_worker(monkeypatch, library):
    import threading

    from thoughtquake.engine import generate

    workers = set()
    pauses = []

    class Recording(MockBackend):
        def prefill(self, *args, **kwargs):
            workers.add(threading.get_ident())
            return super().prefill(*args, **kwargs)

        def step(self, *args, **kwargs):
            workers.add(threading.get_ident())
            return super().step(*args, **kwargs)

    async def sleep(delay):
        pauses.append(delay)

    monkeypatch.setattr(generate.asyncio, "sleep", sleep)

    async def run():
        engine = Generator(Recording(), library, Mixer())
        return [e async for e in engine.stream(answers=3, max_tokens=1, pause=0)]

    events = asyncio.run(run())
    assert pauses == [2, 2]
    assert len(workers) == 1
    assert threading.get_ident() not in workers
    assert sum(isinstance(e, Token) for e in events) == 3
