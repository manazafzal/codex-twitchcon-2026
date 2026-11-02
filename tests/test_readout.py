import numpy as np
import pytest

from nous.engine.readout import Readout


def test_cosine_margin_is_blind_to_active_candidates(library):
    reader = Readout(library, margin_threshold=0.2)
    h = np.zeros(32)
    h[:3] = [3, 4, 12]
    result = reader.observe(h, ["ocean", "space"])
    assert result.scores["jazz"] == pytest.approx(12 / 13)
    assert result.top == "jazz"
    assert result.margin == pytest.approx(8 / 13)
    assert result.color == "jazz"
    result = reader.observe(h, ["ocean", "space"], secret="jazz")
    assert result.top == result.color == "jazz"
    assert result.margin == pytest.approx(8 / 13)


def test_windowed_mean_baseline_and_reset(library):
    library.HR_neutral[:] = 2
    reader = Readout(library, window=2, margin_threshold=0.1)
    a, b = library.HR_neutral.copy(), library.HR_neutral.copy()
    a[0] += 3
    b[1] += 1
    assert reader.observe(a, ["ocean", "space"]).color == "ocean"
    result = reader.observe(b, ["ocean", "space"])
    assert result.color == "ocean"
    assert result.margin == pytest.approx(2 / np.sqrt(10))
    assert reader.observe(b, ["ocean", "space"]).color == "space"
    reader.reset()
    assert reader.observe(library.HR_neutral, ["ocean", "space"]).color is None
    assert reader.observe(b, []).top == "space"


def test_uncertain_readout_abstains_without_changing_alarm_scores(library):
    reader = Readout(library, margin_threshold=0.1)
    hidden = np.zeros(32)
    hidden[:3] = [1.0, 1.01, 1.0]
    reading = reader.decide(hidden, [])
    assert reading.top is None and reading.color is None
    assert reading.margin < 0.1
    assert reading.scores["space"] > reading.scores["ocean"]
    hidden[:3] = [0, 2, 0]
    assert reader.decide(hidden, []).top == "space"
    assert reader.decide(np.zeros(32), []).top is None
