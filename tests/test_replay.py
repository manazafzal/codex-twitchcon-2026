import asyncio
import json

import pytest

from thoughtquake.engine.events import Badge, Mode, Push, Token
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.replay.player import Player
from thoughtquake.replay.recorder import Recorder


def metadata(library):
    return {
        "config": {"schedule_mode": "answer", "max_tokens": 4},
        "seed": 7,
        "model_slug": "mock",
        "library_hash": library.hash,
        "app_version": "0.1.0",
    }


def test_frames_roundtrip_and_replay_badge(tmp_path, library):
    clock = FakeClock()
    path = tmp_path / "record.jsonl"
    token = Token(
        0, "tea", "ocean", {"scores": {"ocean": 1}, "top": "ocean", "margin": 0.5}, "ocean"
    )
    with Recorder(path, metadata(library), clock=clock) as recorder:
        recorder.record(Badge("SIMULATED ×40", "TINY MODEL / CI"))
        clock.advance(1)
        recorder.record(Mode("war", False, "Tea.", 0))
        recorder.record(token)
    player = Player(path)
    output = list(player.frame_events())
    assert output[0][1].label == "REPLAY"
    assert output[-1] == (1, token)
    assert not any(isinstance(e, Badge) and e.label.startswith("SIMULATED") for _, e in output)
    assert player.metadata["seed"] == 7
    assert recorder.file.closed

    async def run():
        return [event async for event in player.frames(speed=100000)]

    assert len(asyncio.run(run())) == 3


def test_engine_replay_regenerates_from_pushes_not_token_text(tmp_path, library):
    clock = FakeClock()
    engine = Generator(MockBackend(), library, Mixer(clock=clock), seed=7, clock=clock)
    path = tmp_path / "run.jsonl"
    expected = []
    with Recorder(path, metadata(library), clock=clock) as recorder:
        iterator = engine.events(max_tokens=4)
        for event in iterator:
            recorder.record(event)
            if isinstance(event, Mode):
                engine.push(Push("sim_001", "ocean", clock(), "SIMULATED"))
                engine.push(Push("sim_002", "space", clock(), "SIMULATED"))
            if isinstance(event, Token):
                expected.append(event.to_dict())
            clock.advance(0.1)
    # Poison recorded output to demonstrate --engine never copies saved model text.
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if row.get("event", {}).get("kind") == "token":
            row["event"]["text"] = "DO NOT COPY"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    fresh_clock = FakeClock()
    fresh = Generator(MockBackend(), library, Mixer(clock=fresh_clock), seed=7, clock=fresh_clock)
    actual = [
        e.to_dict()
        for _, e in Player(path).engine_events(fresh, fresh_clock)
        if isinstance(e, Token)
    ]
    assert actual == expected


@pytest.mark.parametrize(
    "contents",
    [
        "",
        '{"t": 0, "kind": "frame", "event": {"kind":"badge", "label":"LIVE"}}',
        '{"t": 0, "kind": "meta"}\n{"t": -1, "kind": "meta"}',
    ],
)
def test_invalid_recordings_rejected(tmp_path, contents):
    path = tmp_path / "bad.jsonl"
    path.write_text(contents)
    with pytest.raises(ValueError):
        Player(path)
