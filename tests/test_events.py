import json

import pytest

from nous.engine.events import (
    Badge,
    Mode,
    Push,
    Snapshot,
    Tamper,
    Tick,
    Token,
    event_from_dict,
)


@pytest.mark.parametrize(
    "event",
    [
        Push("sim_001", "ocean", 0, "SIMULATED"),
        Tick({"ocean": 0.75, "Neutral": 0.25}, 1, [], 0),
        Token(
            0, "tea", "ocean", {"scores": {"ocean": 0.8}, "top": "ocean", "margin": 0.5}, "ocean"
        ),
        Mode("attack", True, "Make tea.", 0, panel="on"),
        Tamper(("ocean",), 0.5),
        Badge("SIMULATED ×40", "TINY MODEL / CI"),
        Snapshot({"tokens": []}),
    ],
)
def test_wire_roundtrip(event):
    row = json.loads(json.dumps(event.to_dict(), allow_nan=False))
    assert event_from_dict(row).to_dict() == row


@pytest.mark.parametrize(
    "row",
    [
        {"kind": "unknown"},
        {"kind": "token", "text": "incomplete"},
        {"kind": "badge", "label": "synthetic"},
        {"kind": "badge", "label": "LIVE", "extra": 2},
        {"kind": "tick", "shares": {"ocean": 2}, "beta": 0, "top_pushers": [], "t": 0},
    ],
)
def test_bad_wire_events_rejected(row):
    with pytest.raises(ValueError):
        event_from_dict(row)
