import math

import numpy as np
import pytest

from thoughtquake.engine.events import Push
from thoughtquake.engine.mixer import FakeClock, Mixer


def push(mixer, clock, user, faction="ocean"):
    return mixer.push(Push(user, faction, clock(), "SIMULATED"))


def test_exact_cap_decay_and_beta():
    clock = FakeClock()
    mixer = Mixer(clock=clock)
    for i in range(4):
        assert push(mixer, clock, str(i)) == 1
    tick = mixer.tick()
    assert tick.shares == {"ocean": 0.75, "Neutral": 0.25}
    assert tick.beta == pytest.approx(1.5 * (1 - math.exp(-4 / 3)))
    clock.advance(20)
    tick = mixer.tick()
    assert tick.shares == {"ocean": 0.5, "Neutral": 0.5}
    assert tick.beta == pytest.approx(1.5 * (1 - math.exp(-2 / 3)))
    assert tick.top_pushers == [("0", 0.5), ("1", 0.5), ("2", 0.5), ("3", 0.5)]


def test_exact_spam_control_cross_faction_and_boundaries():
    clock = FakeClock()
    mixer = Mixer(clock=clock)
    assert push(mixer, clock, "a") == 1
    assert push(mixer, clock, "a", "space") == 0.25
    clock.advance(8)
    assert push(mixer, clock, "a") == 1
    assert push(mixer, clock, "a") == 0
    clock.advance(12)
    assert push(mixer, clock, "a") == 1
    assert push(mixer, clock, "a") == 0.25
    assert push(mixer, clock, "a") == 0


def test_top_three_drop_before_total_and_neutral_share():
    clock = FakeClock()
    mixer = Mixer(clock=clock)
    for f, n in [("a", 4), ("b", 3), ("c", 2), ("d", 1)]:
        for i in range(n):
            push(mixer, clock, f"{f}{i}", f)
    assert mixer.tick().shares == {"a": 4 / 9, "b": 3 / 9, "c": 2 / 9, "Neutral": 0}
    assert mixer.tick().beta == pytest.approx(1.5 * (1 - math.exp(-3)))
    quiet = Mixer(clock=clock)
    assert quiet.tick().shares == {"Neutral": 1}
    push(quiet, clock, "a", "a")
    push(quiet, clock, "b", "b")
    assert quiet.tick().shares == pytest.approx(
        {"a": 1 / 3, "b": 1 / 3, "Neutral": 1 / 3}, abs=1e-15
    )


@pytest.mark.parametrize(
    "mode, redraws", [("answer", [0]), ("sentence", [0, 16, 32]), ("token", list(range(33)))]
)
def test_schedule_draw_boundaries(mode, redraws):
    class RNG:
        def __init__(self):
            self.calls = []

        def choice(self, names, p):
            self.calls.append(len(self.calls))
            return names[0]

    clock = FakeClock()
    mixer = Mixer(clock=clock, schedule_mode=mode)
    push(mixer, clock, "a")
    rng = RNG()
    for i in range(33):
        before = len(rng.calls)
        mixer.select(i, rng)
        assert len(rng.calls) - before == int(i in redraws)
    assert np.linalg.norm(mixer.vector({"ocean": np.array([3.0, 4.0])})) == pytest.approx(
        mixer.tick().beta * 10
    )


def test_answer_freezes_strength_until_next_answer():
    clock = FakeClock()
    mixer = Mixer(clock=clock)
    push(mixer, clock, "a")
    # Fixed seed selects ocean for this probability distribution.
    rng = np.random.default_rng(3)
    assert mixer.select(0, rng) == "ocean"
    before = mixer.vector({"ocean": np.array([1.0, 0.0])})
    clock.advance(100)
    mixer.select(1, rng)
    np.testing.assert_array_equal(before, mixer.vector({"ocean": np.array([1.0, 0.0])}))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"beta_max": 2.1},
        {"schedule_mode": "bad"},
        {"half_life": 0},
        {"chunk": 0},
        {"dominance_cap": 0.8},
    ],
)
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        Mixer(**kwargs)
