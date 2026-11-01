import numpy as np
import pytest

from nous.engine.immune import ImmuneMonitor, clamp
from nous.model.backend import DefendSpec


def test_clamp_reduces_to_threshold_and_preserves_orthogonal_components():
    spec = DefendSpec(np.array([[2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]), np.array([0.7, 0.5]))
    hidden = np.array([[3.0, 2.0, 8.0], [-2.0, 0.1, -7.0]])
    result, pre, post = clamp(hidden, spec)
    np.testing.assert_allclose(result, [[0.7, 0.5, 8], [-2, 0.1, -7]])
    assert np.all(post <= spec.thresholds + 1e-12)
    np.testing.assert_allclose(hidden, [[3, 2, 8], [-2, 0.1, -7]])
    np.testing.assert_allclose(pre, [[3, 2], [-2, 0.1]])


def test_chip_three_consecutive_and_answer_average():
    monitor = ImmuneMonitor()

    def observe(value):
        return monitor.observe(("a",), np.array([value]), np.array([min(value, 1)]), np.array([1]))

    assert observe(2).concepts == ()
    assert observe(2).concepts == ()
    assert observe(2).concepts == ("a",)
    assert observe(0).concepts == ()
    assert observe(2).concepts == ()
    assert observe(2).neutralised == pytest.approx(5 * 0.5 / 6)
    monitor.reset()
    decision = monitor.observe(
        ("a",),
        np.zeros(1),
        np.zeros(1),
        np.ones(1),
        readout_top="b",
        margin=0.5,
        margin_threshold=0.2,
        pushed={"a"},
    )
    assert decision.concepts == ("b",)
    assert decision.neutralised == 0


def test_answer_reduction_averages_fired_projections_per_token():
    monitor = ImmuneMonitor()
    first = monitor.observe(
        ("attack", "quiet"), np.array([20.0, 0.01]), np.array([0.1, 0.01]), np.array([0.1, 0.1])
    )
    assert first.neutralised == pytest.approx(0.995)
    second = monitor.observe(
        ("attack", "quiet"), np.array([0.01, 0.01]), np.array([0.01, 0.01]), np.array([0.1, 0.1])
    )
    assert second.neutralised == pytest.approx(0.995 / 2)
    monitor.reset()
    assert monitor.reductions == []


def test_readout_alarm_requires_margin_and_no_matching_push():
    monitor = ImmuneMonitor()

    def reading(margin, pushed):
        return monitor.observe(
            ("a",),
            np.zeros(1),
            np.zeros(1),
            np.ones(1),
            readout_top="a",
            margin=margin,
            margin_threshold=0.2,
            pushed=pushed,
        )

    assert not reading(0.19, set()).concepts
    assert not reading(0.5, {"a"}).concepts
    assert reading(0.2, set()).concepts == ("a",)
