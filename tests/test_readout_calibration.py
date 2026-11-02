from dataclasses import replace

import numpy as np
import pytest

from nous.concepts.library import ConceptLibrary
from nous.concepts.probe import Example
from nous.engine.generate import Generator
from nous.engine.mixer import FakeClock, Mixer
from nous.engine.readout import Readout
from nous.evaluation import fit_readout
from nous.evaluation_data import load_calibration, load_examples, save_examples
from nous.model.mock_backend import MockBackend


def corpus(library, scale=1):
    parts = []
    for split in range(3):
        rows = []
        for k, key in enumerate(library.ids):
            for j in range(4):
                x = np.zeros(32)
                x[k] = (500 + j) * scale
                rows.append(
                    Example(
                        f"split {split} class {key} answer {j}",
                        key,
                        f"family {split}",
                        split * 100 + j,
                        x,
                        "off" if split == 0 else "text",
                    )
                )
        parts.append(rows)
    calibration = []
    for i, strength in enumerate([4, 12, 23, 47]):
        x = np.zeros(32)
        x[i % 3] = strength * scale
        calibration.append(Example(f"idle reply {i}", "", "idle", 90000 + i, x, "neutral"))
    return tuple(parts), calibration


def fixed_fit(monkeypatch, library):
    def fit(*args):
        return {
            "center": np.zeros(32),
            "scale": np.ones(32),
            "weights": np.eye(32)[:3],
            "intercept": np.zeros(3),
            "shrinkage": np.array([0.5]),
        }

    monkeypatch.setattr("nous.evaluation.fit_lda", fit)
    library.config.update(probe_layers=[20], readout_layer=20)


@pytest.mark.parametrize("scale", [1, 7])
def test_fit_calibrates_library_scale_without_using_test_scores(
    library, monkeypatch, tmp_path, scale
):
    fixed_fit(monkeypatch, library)
    parts, idle = corpus(library, scale)
    original_alarm = library.thresholds.copy()
    path = tmp_path / "training.npz"
    save_examples(path, parts, library, calibration=idle)
    fit_readout(library, *parts, calibration=idle, bootstrap=10)
    expected = (np.quantile([4, 12, 23, 47], 0.99) + 500) / 2 * scale
    assert library.config["readout_v4_margin_threshold"] == pytest.approx(expected)
    assert library.provenance["readout_v4"]["margin_calibration"]["idle_n"] == 4
    assert np.array_equal(library.thresholds, original_alarm)
    fitted = tmp_path / "fitted.npz"
    library.save(fitted)
    loaded = ConceptLibrary.load(fitted)
    reader = Readout(loaded)
    for row in idle:
        assert reader.decide(row.features, [], features=row.features).top is None
    for row in parts[0]:
        assert reader.decide(row.features, [], features=row.features).top == row.concept
    # The cosine path remains on its own scale; an explicit override still works.
    assert reader.decide(np.eye(32)[0], []).top == "ocean"
    assert (
        Readout(loaded, margin_threshold=1)
        .decide(idle[0].features, [], features=idle[0].features)
        .top
        == "ocean"
    )
    backend = MockBackend()
    backend.readout_layer = 20
    engine = Generator(backend, loaded, Mixer(clock=FakeClock()))
    assert engine.readout.decide(idle[0].features, [], features=idle[0].features).top is None
    # Existing --data fits reproduce the cutoff, and the held-out scores cannot select it.
    parts2 = load_examples(path, loaded)
    changed_test = [replace(e, features=e.features * 1000) for e in parts2[2]]
    fit_readout(
        loaded, *parts2[:2], changed_test, calibration=load_calibration(path, loaded), bootstrap=10
    )
    assert loaded.config["readout_v4_margin_threshold"] == pytest.approx(expected)


def test_idle_calibration_overlap_still_fails(library, monkeypatch):
    fixed_fit(monkeypatch, library)
    parts, idle = corpus(library)
    for bad in (
        replace(idle[0], text=parts[2][0].text),
        replace(idle[0], family=parts[1][0].family),
        replace(idle[0], seed=parts[0][0].seed),
        idle[1],
    ):
        with pytest.raises(ValueError, match="overlaps"):
            fit_readout(library, *parts, calibration=[bad, idle[1]], bootstrap=10)
