import asyncio

from thoughtquake.engine.events import Badge, Mode, Push, Token
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.replay.player import Player
from thoughtquake.replay.recorder import Recorder
from thoughtquake.server.session import Session, mock_library
from thoughtquake.sim.crowd import Crowd


def test_recorded_session_regenerates_tokens_and_comparison(monkeypatch, tmp_path):
    real_sleep = asyncio.sleep

    async def quick_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", quick_sleep)

    async def record():
        crowd = Crowd(twitch_connected=True)
        session = Session(crowd=crowd, seed=7)
        path = tmp_path / "session.jsonl"
        session.recorder = Recorder(path, session.metadata(), clock=session.clock)
        await session.pending.put(Push("sim_001", "ocean", 0, "SIMULATED"))
        await session.pending.put(Push("sim_002", "space", 0, "SIMULATED"))
        output = []
        stream = session.events()
        try:
            off_seen = False
            on_seen = False
            async for event in stream:
                output.append(event)
                if isinstance(event, Token) and event.i == 31 and not off_seen:
                    session.switch_mode("attack")
                if isinstance(event, Mode) and event.mode == "attack":
                    if event.panel == "off":
                        off_seen = True
                    else:
                        on_seen = True
                if on_seen and isinstance(event, Token) and event.i == 31:
                    break
        finally:
            await stream.aclose()
        assert sum(isinstance(e, Badge) for e in output) == 1
        phases = [e for e in output if isinstance(e, Mode) and e.mode == "attack"]
        assert [e.panel for e in phases] == ["off", "on"]
        assert phases[0].prompt == phases[1].prompt
        assert not phases[0].immune and phases[1].immune
        return path, output

    path, output = asyncio.run(record())
    player = Player(path)
    clock = FakeClock()
    engine = Generator(MockBackend(), mock_library(), Mixer(clock=clock), seed=7, clock=clock)
    regenerated = [
        e.to_dict() for _, e in player.engine_events(engine, clock) if isinstance(e, Token)
    ]
    assert regenerated == [e.to_dict() for e in output if isinstance(e, Token)]
