import asyncio

import numpy as np

from thoughtquake.engine.events import Control, Guess, Immune, Mode, Push, Round, Token
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.game.telepathy import Phase
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.replay.player import Player
from thoughtquake.replay.recorder import Recorder
from thoughtquake.server.session import Session, mock_library
from thoughtquake.sim.crowd import Crowd


def test_telepathy_director_injects_secret_scores_reveals_and_replays(monkeypatch, tmp_path):
    clock = FakeClock()
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        clock.advance(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    class RecordingBackend(MockBackend):
        def __init__(self):
            self.prefills = []

        def prefill(self, prompt, inject=None, defend=None, *, inject_prefill=False):
            self.prefills.append(
                (prompt, inject.copy() if inject is not None else None, defend, inject_prefill)
            )
            return super().prefill(prompt, inject, defend, inject_prefill=inject_prefill)

    async def run():
        backend = RecordingBackend()
        session = Session(backend=backend, crowd=Crowd(twitch_connected=True), clock=clock, seed=9)
        session.switch_mode("telepathy")
        session.pending.put_nowait(Push("a", "ocean", 0, "SIMULATED"))
        session.pending.put_nowait(Push("b", "space", 0, "SIMULATED"))
        path = tmp_path / "telepathy.jsonl"
        session.recorder = Recorder(path, session.metadata(), clock=clock)
        stream = session.events()
        output, guessed = [], False
        try:
            async for event in stream:
                output.append(event)
                if isinstance(event, Mode) and event.phase == "guessing" and not guessed:
                    secret = session.telepathy.secret
                    assert secret not in {"ocean", "space"}
                    concept = next(c for c in session.library.concepts if c.id == secret)
                    session.pending.put_nowait(
                        Guess("Winner", concept.aliases[0].upper(), clock(), "SIMULATED", "42")
                    )
                    session.pending.put_nowait(Guess("Late", secret, clock(), "SIMULATED", "43"))
                    guessed = True
                if isinstance(event, Mode) and event.phase == "reveal":
                    assert event.winner == "Winner"
                    assert event.scoreboard == (("Winner", 1),)
                    assert event.reveal == secret
                    assert event.probe_top == secret
                    assert event.probe_accuracy is None
                if isinstance(event, Mode) and event.phase == "idle":
                    break
        finally:
            await stream.aclose()
        assert session.telepathy.phase == Phase.IDLE
        assert session.engine.secret is None
        phases = [e.phase for e in output if isinstance(e, Mode)]
        assert phases[0:2] == ["armed", "generating"]
        assert phases[-2:] == ["reveal", "idle"]
        assert sum(isinstance(e, Round) and e.phase == "reveal" for e in output) == 1
        assert len(backend.prefills) == 1
        prompt, vector, defend, prefill = backend.prefills[0]
        assert prompt.startswith("Explain how")
        assert prefill and defend is None
        assert np.linalg.norm(vector) == 20
        assert len([e for e in output if isinstance(e, Token)]) == 32
        return path, output

    path, output = asyncio.run(run())
    replay_clock = FakeClock()
    engine = Generator(
        MockBackend(), mock_library(), Mixer(clock=replay_clock), seed=9, clock=replay_clock
    )
    replayed = [e for _, e in Player(path).engine_events(engine, replay_clock)]
    assert [e.to_dict() for e in replayed if isinstance(e, Token)] == [
        e.to_dict() for e in output if isinstance(e, Token)
    ]
    reveal = next(e for e in replayed if isinstance(e, Mode) and e.phase == "reveal")
    assert reveal.winner == "Winner" and reveal.scoreboard == (("Winner", 1),)


def test_director_timeout_and_immune_persists_back_to_war(monkeypatch):
    clock = FakeClock()
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        clock.advance(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    async def run():
        session = Session(crowd=Crowd(twitch_connected=True), clock=clock)
        session.set_immune(True)
        session.switch_mode("telepathy")
        output = []
        stream = session.events()
        try:
            async for event in stream:
                output.append(event)
                if isinstance(event, Mode) and event.phase == "reveal":
                    assert event.winner is None and not event.scoreboard
                    session.switch_mode("war")
                if isinstance(event, Mode) and event.mode == "war":
                    assert event.immune
                    break
        finally:
            await stream.aclose()
        assert any(isinstance(e, Immune) and not e.enabled for e in output)
        assert len([e for e in output if isinstance(e, Control)]) == 1
        assert session.immune_enabled
        guessing = [e for e in output if isinstance(e, Mode) and e.phase == "guessing"]
        assert guessing[0].remaining == 30
        assert 0 < guessing[-1].remaining <= 0.1

    asyncio.run(run())


def test_toggle_immune_applies_to_next_model_call(monkeypatch):
    real_sleep = asyncio.sleep

    async def sleep(_):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    class RecordingBackend(MockBackend):
        def __init__(self):
            self.defences = []

        def step(self, state, token, inject=None, defend=None):
            self.defences.append(defend is not None)
            return super().step(state, token, inject, defend)

    async def run():
        backend = RecordingBackend()
        session = Session(backend=backend, crowd=Crowd(twitch_connected=True))
        stream = session.events()
        try:
            async for event in stream:
                if isinstance(event, Token) and event.i == 0:
                    session.set_immune(True)
                if isinstance(event, Token) and event.i == 1:
                    break
        finally:
            await stream.aclose()
        assert backend.defences == [False, True]

    asyncio.run(run())
