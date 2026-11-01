import json

import numpy as np
import pytest

from nous.engine.events import Push, Token
from nous.engine.generate import Generator
from nous.engine.mixer import FakeClock, Mixer
from nous.model.mock_backend import MockBackend


class ChangingHidden(MockBackend):
    def step(self, state, token, inject=None, defend=None):
        logits, _, result = super().step(state, token, inject, defend)
        hidden = np.zeros(32)
        hidden[0 if result.position <= 8 else 1] = 1
        return logits, hidden, result


@pytest.mark.parametrize("schedule", ["answer", "token", "sentence"])
def test_readout_colour_uses_whole_answer_or_window_mean(tmp_path, library, schedule):
    evidence = tmp_path / "eval.json"
    evidence.write_text(
        json.dumps({"source": "realmodel", "schedule_modes": {schedule: {"window_agreement": 0.9}}})
    )
    clock = FakeClock()
    mixer = Mixer(clock=clock, schedule_mode=schedule)
    engine = Generator(
        ChangingHidden(), library, mixer, clock=clock, colour_source="readout", eval_path=evidence
    )
    for i, faction in enumerate(library.ids):
        engine.push(Push(str(i), faction, 0, "SIMULATED"))
    frames = [e for e in engine.events(max_tokens=24) if isinstance(e, Token)]
    assert [e.i for e in frames] == list(range(24))
    if schedule == "answer":
        assert {e.color for e in frames} == {"space"}
    else:
        assert {e.color for e in frames[:12]} == {"ocean"}
        assert {e.color for e in frames[12:]} == {"space"}
    # Raw probe scores still vary per token; the displayed colour does not follow each token.
    assert frames[0].readout["top"] == "ocean"
    assert frames[-1].readout["top"] == "space"


def test_applied_token_experiment_still_colours_whole_windows(library):
    clock = FakeClock()
    mixer = Mixer(clock=clock, schedule_mode="token")
    engine = Generator(MockBackend(), library, mixer, clock=clock, seed=7)
    for i, faction in enumerate(library.ids):
        engine.push(Push(str(i), faction, 0, "SIMULATED"))
    frames = [e for e in engine.events(max_tokens=24) if isinstance(e, Token)]
    assert len({e.applied for e in frames}) > 1
    assert len({e.color for e in frames[:12]}) == 1
    assert len({e.color for e in frames[12:]}) == 1
