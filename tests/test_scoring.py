import multiprocessing
import os
import signal

import pytest

from nous.engine.mixer import FakeClock
from nous.server.leaderboard import Leaderboard
from nous.server.scoring import Scoring


def test_scoring_formula_cooldown_caps_and_guess_ranks():
    clock = FakeClock()
    score = Scoring(clock=clock)
    assert score.push("a", "A", "ocean", 1)
    assert not score.push("a", "A", "ocean", 1)
    assert score.push("b", "B", "ocean", 1)
    assert score.push("c", "C", "space", 1)
    score.finish({"ocean": 1, "space": 0})
    assert score.board.stream["a"]["points"] == pytest.approx(20 / 3)
    assert score.board.stream["b"]["points"] == pytest.approx(20 / 3)
    assert "c" not in score.board.stream
    score.begin(1)
    for i, expected in enumerate((100, 60, 40, 25, 15, 10, 10)):
        assert score.guess(str(i), str(i), correct=True) == expected
    assert score.guess("0", "0", correct=True) == 0
    assert score.catch("0", "0", true_concept="ocean", attributed=("space",), immune=True) == 0
    assert score.catch("0", "0", true_concept="ocean", attributed=("ocean",), immune=True) == 15
    assert score.catch("0", "0", true_concept="ocean", attributed=("ocean",), immune=True) == 0
    for _ in range(1000):
        score.push("spam", "Spam", "ocean", 1)
        clock.advance(0.01)
    assert score.guess("careful", "Careful", correct=True) > 0
    score.finish({"ocean": 1})
    assert score.board.stream["spam"]["points"] <= 20
    # A first careful guess always outranks the entire push budget.
    second = Scoring(clock=clock)
    for _ in range(1000):
        second.push("spam", "Spam", "ocean", 1)
        clock.advance(0.01)
    second.guess("careful", "Careful", correct=True)
    second.finish({"ocean": 1})
    assert second.board.stream["spam"]["points"] < second.board.stream["careful"]["points"]
    assert max(second.round_points.values()) <= 120


def test_roundtrip_and_failed_replace_preserve_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "scores.json"
    board = Leaderboard(path)
    board.add("1", "Viewer", 7, "ocean")
    board.save()
    loaded = Leaderboard(path)
    assert loaded.all_time == board.all_time and not loaded.stream

    def fail(source, target):
        raise OSError("Interrupted replacement")

    monkeypatch.setattr(os, "replace", fail)
    board.add("2", "Other", 5, "space")
    with pytest.raises(OSError):
        board.save()
    assert Leaderboard(path).all_time == loaded.all_time


def paused_writer(path, child):
    def pause(source, target):
        child.send("ready")
        signal.pause()

    os.replace = pause
    changed = Leaderboard(path)
    changed.add("2", "Other", 99)
    changed.save()


def test_kill_before_atomic_replace_keeps_valid_target(tmp_path):
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("POSIX crash check")
    path = tmp_path / "scores.json"
    board = Leaderboard(path)
    board.add("1", "Viewer", 7)
    board.save()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()

    process = context.Process(target=paused_writer, args=(path, child))
    process.start()
    try:
        assert parent.poll(5) and parent.recv() == "ready"
        os.kill(process.pid, signal.SIGKILL)
        process.join(5)
        assert list(Leaderboard(path).all_time) == ["1"]
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        parent.close()
        child.close()
