import pytest

from thoughtquake.concepts.library import load_concepts
from thoughtquake.engine.mixer import FakeClock
from thoughtquake.game.telepathy import Phase, Telepathy


def game():
    clock = FakeClock()
    return Telepathy(load_concepts(), clock=clock, seed=3), clock


def start(round, secret="ocean"):
    assert round.arm({"space", "jazz"}, secret=secret) == secret
    assert round.phase == Phase.ARMED
    round.start()
    assert round.phase == Phase.GENERATING
    round.finish_generation({"ocean": 0.7, "space": 0.2, "jazz": 0.1})
    assert round.phase == Phase.GUESSING


def test_state_machine_first_correct_alias_wins_once():
    round, clock = game()
    assert round.phase == Phase.IDLE
    assert not round.guess("early", "sea")
    start(round)
    assert round.remaining == 30
    assert not round.guess("wrong", "STAR")
    clock.advance(1)
    assert round.guess("Friend", "SEA", user_id="300")
    assert round.phase == Phase.REVEAL
    assert round.winner == "Friend"
    assert round.probe_top == "ocean"
    assert round.candidates == ("ocean", "space", "jazz")
    assert round.scoreboard == (("Friend", 1),)
    assert not round.guess("other", "ocean")
    assert not round.guess("Friend", "ocean", user_id="300")
    round.reset()
    assert round.phase == Phase.IDLE and round.secret is None
    start(round)
    assert round.guess("Renamed", "!guess tide", user_id="300")
    assert round.scoreboard == (("Renamed", 2),)


def test_timeout_and_exact_deadline_reject_guess():
    round, clock = game()
    start(round)
    clock.advance(29.9)
    assert round.tick() == Phase.GUESSING
    clock.advance(0.1)
    assert not round.guess("late", "sea")
    assert round.phase == Phase.REVEAL and round.winner is None
    assert not round.scoreboard
    assert round.remaining == 0


def test_inactive_secret_selection_is_seeded_and_invalid_transitions_fail():
    first, _ = game()
    second, _ = game()
    assert first.arm({"ocean", "space", "jazz"}) == second.arm({"ocean", "space", "jazz"})
    assert first.secret not in {"ocean", "space", "jazz"}
    with pytest.raises(ValueError):
        first.arm(set())
    with pytest.raises(ValueError):
        second.reset()
    first.cancel()
    with pytest.raises(ValueError):
        first.start()
    with pytest.raises(ValueError):
        first.arm({first_id.id for first_id in first.concepts})


def test_scoreboard_keeps_top_five_with_stable_ties():
    round, _ = game()
    for i in range(7):
        start(round)
        assert round.guess(f"user{i}", "sea")
        round.reset()
    assert round.scoreboard == tuple((f"user{i}", 1) for i in range(5))
