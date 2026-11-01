import json
from dataclasses import replace

import numpy as np
import pytest

from thoughtquake.concepts.library import ConceptLibrary, load_concepts
from thoughtquake.concepts.probe import Example, check_partitions, fit_lda, lda_scores
from thoughtquake.engine.events import Push, Tamper
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.immune import AlarmMonitor
from thoughtquake.engine.mixer import FakeClock, ForcedMixer
from thoughtquake.engine.readout import Readout
from thoughtquake.evaluation import (
    METRICS,
    Trial,
    estimate,
    evaluate,
    fit_readout,
    validate_report,
    wilson,
    write_report,
)
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.server.session import mock_library


def test_others_vectors_calibration_and_all_array_checks(monkeypatch, tmp_path):
    from thoughtquake.concepts import builder

    class Backend:
        injection_layer, readout_layer, hidden_size, num_layers = 16, 20, 3, 24

    means = {
        "Ocean": np.array([2.0, 0, 1]),
        "Space": np.array([0.0, 4, 1]),
        "Jazz": np.array([0.0, 0, 7]),
    }

    def answer(backend, prompt, rng, max_tokens=32):
        v = next(value for key, value in means.items() if key in prompt)
        return (
            prompt,
            {16: np.stack([v, v]), 20: np.stack([2 * v, 2 * v]), 22: np.stack([3 * v, 3 * v])},
            np.stack([v, v]),
        )

    def neutral(backend, count, seed):
        result = []
        for i in range(count):
            v = np.array([1 + i / 100, 2 + i / 200, 3 + i / 300])
            result.append(
                (
                    f"ordinary output {seed} {i}",
                    {16: v[None, :], 20: 2 * v[None, :], 22: 3 * v[None, :]},
                    (v + seed)[None, :],
                )
            )
        return result

    monkeypatch.setattr(builder, "trace_answer", answer)
    monkeypatch.setattr(builder, "neutral_set", neutral)
    library = builder.build_library(Backend(), load_concepts()[:3], samples=1)
    expected = np.stack(list(means.values()))
    from thoughtquake.engine.immune import unit

    np.testing.assert_allclose(library.V, unit(expected - (expected.sum(axis=0) - expected) / 2))
    assert library.config["excluded_positions"] == [0]
    assert library.config["injection_layer"] == 16 and library.config["readout_layer"] == 20
    assert library.config["neutral_samples"] >= 60
    assert library.config["alarm_seed"] == 1
    assert len(library.vector_hashes) == 3
    p = tmp_path / "library.npz"
    library.save(p)
    assert ConceptLibrary.load(p).hash == library.hash
    with np.load(p) as source:
        original = dict(source)
    for key in ("V_norms", "readout_mean", "alarm_thresholds"):
        changed = dict(original)
        changed[key] = changed[key] + 1
        np.savez(p, **changed)
        with pytest.raises(ValueError, match="content hash"):
            ConceptLibrary.load(p)
    assert all(-1 <= v <= 1 for point in library.layout().values() for v in point)
    assert library.mentioned_in("Waves and gardening") == {"ocean"}


def test_blind_all_concepts_and_z_calibration():
    library = mock_library()
    library.readout_mean = np.zeros(30)
    library.readout_std = np.full(30, 0.2)
    hidden = np.zeros(32)
    hidden[29] = 1
    reading = Readout(library).observe(hidden, [library.ids[0]], secret=library.ids[1])
    assert reading.top == library.ids[29]
    assert reading.scores[reading.top] == pytest.approx(5)
    assert len(reading.scores) == 30


def test_alpha_strength_zero_and_eval_cap():
    clock = FakeClock()
    mixer = ForcedMixer("ocean", alpha=0.45, median_norm=26.78, clock=clock)
    for i in range(60):
        mixer.push(Push(str(i), "ocean", 0, "SIMULATED"))
    mixer.select(0, np.random.default_rng(0))
    assert mixer.selected == "ocean" and mixer.tick().shares["ocean"] == 0.75
    assert mixer.tick().beta <= 1
    assert np.linalg.norm(mixer.vector({"ocean": np.array([2.0, 0.0])})) == pytest.approx(
        0.45 * 26.78 * (1 - np.exp(-60 / 3))
    )
    with pytest.raises(ValueError):
        ForcedMixer("ocean", alpha=0.51, median_norm=26.78)
    zero = ForcedMixer("ocean", alpha=0, median_norm=26.78, clock=clock)
    zero.push(Push("a", "ocean", 0, "SIMULATED"))
    zero.select(0, np.random.default_rng(0))
    assert not np.any(zero.vector({"ocean": np.ones(32)}))


def test_alarm_same_concept_run_eight_exemption_and_neutral_regression():
    monitor = AlarmMonitor()
    ids = ("first", "second")
    threshold = np.array([10.0, 10.0])
    # Six off-topic spikes used to fire a shorter rule; the new run must remain silent.
    for i in range(6):
        decision = monitor.observe(
            ids, np.array([11.0, 0]), np.array([1.0, 0]), threshold, {}, exempt=set()
        )
        assert not decision.fired
    assert monitor.max_run == 6
    monitor.observe(ids, np.zeros(2), np.zeros(2), threshold, {}, exempt=set())
    for i in range(8):
        decision = monitor.observe(
            ids, np.array([11.0, 0]), np.array([1.0, 0]), threshold, {}, exempt=set()
        )
        assert decision.fired == (i == 7)
    monitor.reset()
    for _ in range(10):
        assert not monitor.observe(
            ids, np.array([99.0, 0]), np.zeros(2), threshold, {"first": 8}, exempt={"first"}
        ).fired
    monitor.reset()
    for i in range(8):
        result = monitor.observe(
            ids, np.zeros(2), np.zeros(2), threshold, {"second": 4}, exempt=set()
        )
    assert result.fired and result.concept == "second"
    monitor.observe(ids, np.array([11.0, 0]), np.zeros(2), threshold, {}, exempt=set())
    assert monitor.run == 1


def partitions():
    rng = np.random.default_rng(1)
    result = []
    for split, seeds in (("train", range(5)), ("val", range(100, 103)), ("test", range(200, 204))):
        rows = []
        for k, key in enumerate(("ocean", "space", "jazz")):
            center = np.eye(3)[k]
            for seed in seeds:
                features = np.concatenate([center, center]) + rng.normal(0, 0.03, 6)
                rows.append(Example(f"{split} document {key} {seed}", key, split, seed, features))
        result.append(rows)
    return tuple(result)


def test_lda_disjoint_families_seeds_hashes_and_roundtrip(tmp_path):
    train, val, test = partitions()
    check_partitions(train, val, test)
    for bad in (
        replace(val[0], family=train[0].family),
        replace(val[0], seed=train[0].seed),
        replace(val[0], text=train[0].text.upper()),
    ):
        with pytest.raises(ValueError, match="overlap"):
            check_partitions(train, [bad], test)
    library = ConceptLibrary(
        load_concepts()[:3],
        np.ones((3, 2)),
        np.array([[1.0, 0], [0, 1], [-1, -1]]),
        np.zeros(2),
        np.ones(3),
        {"model": "mock", "probe_layers": [16, 20, 22], "readout_layer": 20},
    )
    report = fit_readout(library, train, val, test)
    assert report["n"] == 12 and report["metrics"]["readout_top1"]["n"] == 12
    assert report["metrics"]["readout_top1"]["mean"] > 0.9
    weights = fit_lda(train, library.ids)
    assert np.argmax(lda_scores(weights, test[0].features)) == 0
    path = tmp_path / "fit.npz"
    library.save(path)
    loaded = ConceptLibrary.load(path)
    assert loaded.hash == library.hash
    with np.load(path) as source:
        data = dict(source)
    data["v4_weights"] = data["v4_weights"] + 1
    np.savez(path, **data)
    with pytest.raises(ValueError, match="content hash"):
        ConceptLibrary.load(path)


def test_cluster_bootstrap_resamples_concepts_not_individual_answers():
    rows = [Trial("first", "p", i, 0, False, {"metric": (1.0, 1.0)}, "", 1) for i in range(10)]
    rows += [Trial("second", "p", i, 0, False, {"metric": (0.0, 1.0)}, "", 1) for i in range(10)]
    result = estimate(rows, "metric")
    assert result["n"] == 20 and result["clusters"] == 2 and result["mean"] == 0.5
    assert result["cluster_ci95"] == [0, 1]
    assert result == estimate(rows, "metric")
    assert wilson(0, 10)[0] == 0


def test_matched_eval_schema_table_and_no_off_tamper(tmp_path):
    library = mock_library()
    library.config.update(probe_layers=[11], readout_layer=11)
    report = evaluate(
        MockBackend(),
        library,
        alphas=[0.3, 0.45],
        seeds=1,
        prompts=1,
        concepts=3,
        held_out=1,
        source="mock",
    )
    validate_report(report)
    assert {row["n"] for row in report["rows"]} == {3}
    assert report["quality"] == "TINY MODEL / CI"
    assert len(report["embed_tau"]) == 30
    assert all(list(row["metrics"]) == list(METRICS) for row in report["rows"])
    assert all(row["metrics"]["readout_top1"]["mean"] is None for row in report["rows"])
    write_report(report, tmp_path)
    header = next(
        line
        for line in (tmp_path / "eval.md").read_text().splitlines()
        if line.startswith("| alpha")
    )
    assert [s.strip() for s in header.strip("|").split("|")][3:] == list(METRICS)
    assert json.loads((tmp_path / "eval.json").read_text())["n"] == report["n"]
    engine = Generator(
        MockBackend(),
        library,
        ForcedMixer("ocean", alpha=0, median_norm=26.78, clock=FakeClock()),
        immune=False,
    )
    assert not any(isinstance(e, Tamper) for e in engine.events(max_tokens=4))
    with pytest.raises(ValueError, match="trained local"):
        evaluate(MockBackend(), library, alphas=[0.45], seeds=1, prompts=1, concepts=3)


def test_v4_labels_do_not_change_projection_alarm():
    library = mock_library()
    library.config["probe_layers"] = [16, 20, 22]
    library.readout_mean = np.zeros(30)
    library.readout_std = np.full(30, 0.2)
    library.readout_v4 = {
        "center": np.zeros(96),
        "scale": np.ones(96),
        "weights": np.zeros((30, 96)),
        "intercept": np.eye(30)[2] * 100,
        "shrinkage": np.array([0.2]),
    }
    hidden = np.eye(32)[0]
    reading = Readout(library).observe(hidden, [], layers={16: hidden, 20: hidden, 22: hidden})
    assert reading.top == library.ids[2] and reading.scores[library.ids[0]] == 5
    monitor = AlarmMonitor()
    for _ in range(8):
        alarm = monitor.observe(
            library.ids,
            np.zeros(30),
            np.zeros(30),
            np.full(30, np.inf),
            reading.scores,
            exempt=set(),
        )
    assert alarm.fired and alarm.concept == library.ids[0]
    monitor.reset()
    for _ in range(10):
        alarm = monitor.observe(
            library.ids,
            np.zeros(30),
            np.zeros(30),
            np.ones(30),
            dict.fromkeys(library.ids, 0),
            exempt=set(),
        )
        assert not alarm.fired


def test_alpha_zero_text_detector_control_has_no_hit():
    class PlainBackend(MockBackend):
        def decode(self, tokens):
            return " ".join("plain" for _ in tokens)

    library = mock_library()
    library.config.update(probe_layers=[11], readout_layer=11)
    result = evaluate(
        PlainBackend(),
        library,
        alphas=[0.45],
        seeds=1,
        prompts=1,
        concepts=30,
        held_out=0,
        source="mock",
    )
    for row in result["rows"]:
        if row["alpha"] == 0:
            assert row["metrics"]["keyword_hit"]["mean"] == 0
            assert row["metrics"]["stem_hit"]["mean"] == 0
            assert row["metrics"]["embed_hit"]["mean"] == 0


def test_training_data_basis_survives_fitting(tmp_path):
    from thoughtquake.evaluation_data import load_examples, save_examples

    library = ConceptLibrary(
        load_concepts()[:3],
        np.ones((3, 2)),
        np.array([[1.0, 0], [0, 1], [-1, -1]]),
        np.zeros(2),
        np.ones(3),
        {"model": "mock", "probe_layers": [16, 20, 22], "readout_layer": 20},
    )
    parts = partitions()
    path = tmp_path / "examples.npz"
    save_examples(path, parts, library)
    fit_readout(library, *parts)
    restored = load_examples(path, library)
    assert [len(part) for part in restored] == [len(part) for part in parts]
    library.V[0, 0] += 1
    with pytest.raises(ValueError, match="different library"):
        load_examples(path, library)


def test_fixed_rounds_preserve_modern_alpha_and_legacy_strength():
    from thoughtquake.engine.mixer import Mixer
    from thoughtquake.engine.rounds import FixedInjection

    for war, expected in ((Mixer(alpha=0.45, median_norm=26.78), 0.45 * 26.78), (Mixer(), 20)):
        fixed = FixedInjection(war, "ocean")
        fixed.select(0, np.random.default_rng(0))
        assert np.linalg.norm(fixed.vector({"ocean": np.ones(32)})) == pytest.approx(expected)


def test_eval_rejects_fitted_seed_overlap():
    library = mock_library()
    library.provenance["readout_v4"] = {"partitions": {"validation": {"seeds": [0]}}}
    with pytest.raises(ValueError, match="seeds overlap"):
        evaluate(
            MockBackend(), library, alphas=[0.45], seeds=1, prompts=1, concepts=1, source="mock"
        )


def test_fit_cli_reuses_local_split_data_without_loading_model(tmp_path, monkeypatch):
    from thoughtquake.cli import main
    from thoughtquake.evaluation_data import save_examples
    from thoughtquake.model.hf_backend import HFBackend

    train, validation, test = partitions()
    library = ConceptLibrary(
        load_concepts()[:3],
        np.ones((3, 2)),
        np.array([[1.0, 0], [0, 1], [-1, -1]]),
        np.zeros(2),
        np.ones(3),
        {"model": "mock", "probe_layers": [16, 20, 22], "readout_layer": 20},
    )
    path, data, output = tmp_path / "base.npz", tmp_path / "data.npz", tmp_path / "fit.npz"
    library.save(path)
    save_examples(data, (train, validation, test), library)

    def forbidden(*args, **kwargs):
        raise AssertionError("Precomputed fitting must not load model weights")

    monkeypatch.setattr(HFBackend, "__init__", forbidden)
    main(["fit-readout", "--library", str(path), "--data", str(data), "--output", str(output)])
    fitted = ConceptLibrary.load(output)
    assert fitted.readout_v4 and fitted.provenance["readout_dataset_hash"]
    report = json.loads(output.with_suffix(".fit.json").read_text())
    assert report["quality"] == "TINY MODEL / CI" and report["n"] == 12
