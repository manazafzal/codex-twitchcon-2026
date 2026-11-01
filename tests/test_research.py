"""Synthetic algorithm checks, never trained-model quality evidence."""

import copy
import hashlib
import json

import numpy as np
import pytest

from nous.concepts.probe import Example
from nous.engine.events import Push
from nous.engine.mixer import FakeClock, Mixer
from nous.research.alarms import detect
from nous.research.capture import ResearchMixer
from nous.research.classifiers import fit_variant
from nous.research.design import ROOT, cell_id, load_config, plan
from nous.research.paper import main as paper_main
from nous.research.paper import render, validate_source
from nous.research.runner import blank, conclusions, run_research, verify_registration
from nous.research.statistics import paired, reduction, summary
from nous.research.vectors import construct


def test_registration_is_an_unchanged_file_only_commit():
    verify_registration()


def test_registered_grids_and_matched_controls():
    cells = plan(load_config(ROOT / "configs/ablations.yaml"))
    assert {c["layer"] for c in cells["injection_layer"]} == {4, 8, 9, 12, 13, 16, 18, 20}
    assert {c["readout"] for c in cells["readout_layer"]} == set(range(12, 23))
    assert {c["alpha"] for c in cells["dose"]} == {0, 0.15, 0.3, 0.45, 0.6, 0.75, 1, 1.25, 1.5}
    assert {c["vector"] for c in cells["vector"]} == {
        "others",
        "neutral",
        "raw",
        "paired",
        "whitened",
        "random",
    }
    assert len(cells["v4"]) == 150
    assert len(cells["alarm"]) == 800
    for name in ["injection_layer", "readout_layer", "vector"]:
        key = {"injection_layer": "layer", "readout_layer": "readout", "vector": "vector"}[name]
        for value in {c[key] for c in cells[name]}:
            assert {c["alpha"] for c in cells[name] if c[key] == value} == {0, 0.45}
    assert cell_id(cells["dose"][0]) == cell_id(dict(reversed(list(cells["dose"][0].items()))))


def test_changed_design_rejected(tmp_path):
    import yaml

    config = load_config(ROOT / "configs/ablations.yaml")
    config["alphas"] = [0, 0.45]
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="Unregistered"):
        load_config(path)


def test_bootstrap_resamples_concepts_not_answers_and_is_seeded():
    values = {(c, str(i), 0): float(c == "a") for c in ["a", "b"] for i in range(10)}
    result = summary(values)
    assert result["n"] == 20 and result["clusters"] == 2
    assert result["mean"] == 0.5
    assert result["cluster_ci95"] == [0, 1]
    assert result == summary(dict(reversed(list(values.items()))))
    assert result["wilson95"] != result["cluster_ci95"]


def test_pairing_before_cluster_resampling_and_missing_pair_rejected():
    a = {(c, str(i), 0): float(i % 2) for c in ["a", "b"] for i in range(6)}
    result = paired(a, {k: v - 0.25 for k, v in a.items()})
    assert result["mean"] == 0.25 and result["cluster_ci95"] == [0.25, 0.25]
    assert result["n"] == 12 and result["clusters"] == 2
    with pytest.raises(ValueError, match="identical"):
        paired(a, dict(list(a.items())[:-1]))


def test_zero_control_makes_relative_reduction_unavailable():
    off = {("a", "p", 0): 0.0, ("b", "p", 0): 0.0}
    result = reduction(off, off)
    assert result["mean"] is None and result["cluster_ci95"] is None
    assert result["undefined_resamples"] == 2000
    result = reduction(dict.fromkeys(off, 1.0), dict.fromkeys(off, 0.2))
    assert result["mean"] == pytest.approx(0.8)
    assert result["cluster_ci95"] == pytest.approx([0.8, 0.8])


def test_vector_constructions_are_distinct_unit_directions():
    means = np.array([[2.0, 0], [0, 1], [-1, -2]])
    neutral = np.array([0.5, 0.5])
    pair = np.array([[0.0, 0.1], [0.1, 0], [1, 0]])
    covariance = np.diag([1.0, 4])

    def vector(method):
        return construct(means, neutral, pair, covariance, method, seed=4)

    expected = means - (means.sum(axis=0) - means) / 2
    np.testing.assert_allclose(
        vector("others"), expected / np.linalg.norm(expected, axis=1)[:, None]
    )
    for method in ["others", "neutral", "raw", "paired", "whitened", "random"]:
        np.testing.assert_allclose(np.linalg.norm(vector(method), axis=1), 1)
    assert not np.allclose(vector("raw"), vector("others"))
    assert not np.allclose(vector("paired"), vector("neutral"))
    np.testing.assert_array_equal(vector("random"), vector("random"))


def test_research_dose_does_not_relax_production_limits():
    clock = FakeClock()
    mixer = ResearchMixer("a", 1.5, 26.78, clock)
    for i in range(60):
        mixer.push(Push(f"sim_{i}", "a", 0, "SIMULATED"))
    vector = mixer.vector({"a": np.array([3.0, 4.0])})
    np.testing.assert_allclose(np.linalg.norm(vector), 1.5 * 26.78 * mixer.tick().beta)
    assert mixer.tick().shares["a"] == 0.75
    with pytest.raises(ValueError):
        Mixer(alpha=1.5)


def split_data(offset, family, count):
    rng = np.random.default_rng(offset)
    return [
        Example(
            f"{family} distinct sample {key} {i}",
            key,
            family,
            offset + i,
            np.tile(rng.normal(size=2) + np.array([3, -3]) * (1 if key == "a" else -1), 3),
        )
        for key in ["a", "b"]
        for i in range(count)
    ]


@pytest.mark.parametrize("classifier", ["lda", "logistic"])
@pytest.mark.parametrize("whitening", ["none", "standardize", "zca"])
def test_classifier_selection_ignores_test_outcomes(classifier, whitening):
    train, val, test = (
        split_data(1, "train", 8),
        split_data(100, "val", 3),
        split_data(200, "test", 4),
    )
    variant = {
        "layers": [16, 20, 22],
        "whitening": whitening,
        "classifier": classifier,
        "train_size": 8,
    }
    a = fit_variant(train, val, test, ("a", "b"), 2, variant)
    altered = [
        Example(e.text, "b" if e.concept == "a" else "a", e.family, e.seed, e.features * 100)
        for e in test
    ]
    b = fit_variant(train, val, altered, ("a", "b"), 2, variant)
    np.testing.assert_array_equal(a.weights, b.weights)
    np.testing.assert_array_equal(a.transform, b.transform)
    assert a.regularization == b.regularization
    assert a.validation_accuracy == b.validation_accuracy


def test_readout_overlap_is_a_failure_not_a_dropped_sample():
    train, val, test = (
        split_data(1, "train", 8),
        split_data(100, "val", 3),
        split_data(200, "test", 4),
    )
    val[0] = train[0]
    with pytest.raises(ValueError, match="overlap"):
        fit_variant(
            train,
            val,
            test,
            ("a", "b"),
            2,
            {"layers": [20], "whitening": "standardize", "classifier": "lda", "train_size": 8},
        )


def test_alarm_same_concept_run_and_topical_exemption():
    projection = np.zeros((12, 2))
    z = np.tile([5.0, 0.0], (12, 1))
    result = detect(projection, z, np.ones(2))
    assert result["flagged"] == {0} and result["max_run"] == 12
    assert detect(projection, z, np.ones(2), exempt={0})["any_alarm"] == 0
    alternating = np.array([[5.0, 0.0], [0.0, 5.0]] * 6)
    assert detect(projection, alternating, np.ones(2))["any_alarm"] == 0
    # Projection equality is not an alarm; equality at the z cutoff is.
    assert detect(np.ones((12, 2)), np.zeros((12, 2)), np.ones(2))["any_alarm"] == 0
    assert detect(projection, z * 0.8, np.ones(2))["any_alarm"] == 1


def test_interval_crossing_zero_is_inconclusive_not_unrun():
    tables = {
        name: [blank(c, "absent") for c in rows]
        for name, rows in plan(load_config(ROOT / "configs/ablations.yaml")).items()
    }
    tables["paired"] = [
        {
            "comparison": "H1 dose minus control",
            "status": "run",
            "n": 180,
            "mean": 0.1,
            "cluster_ci95": [-0.1, 0.2],
        }
    ]
    result = conclusions(tables)[0]
    assert result["status"] == "run" and result["decision"] == "inconclusive"
    assert result["n"] == 180


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    pytest.importorskip("matplotlib")
    path = tmp_path_factory.mktemp("research")
    # Explicitly no artifacts, regardless of a developer's local model setting.
    from unittest.mock import patch

    with patch.dict("os.environ", {"NOUS_MODEL_PATH": ""}):
        result = run_research(ROOT / "configs/ablations.yaml", 0, path)
    return path, result


def test_offline_missing_model_has_no_invented_results(evidence):
    path, result = evidence
    for name, rows in result["tables"].items():
        assert all(row["status"] == "unrun" and row["n"] == 0 for row in rows)
        for extension in ["csv", "json", "md"]:
            assert (path / "tables" / f"{name}.{extension}").is_file()
    assert len(list((path / "figures").glob("*.svg"))) == 10
    assert len(list((path / "figures").glob("*.png"))) == 10
    assert result["manifest"]["source"] == "realmodel"
    assert not result["manifest"]["provenance"]


def test_same_seed_produces_identical_tables_and_figures(evidence, tmp_path, monkeypatch):
    first, _ = evidence
    monkeypatch.delenv("NOUS_MODEL_PATH", raising=False)
    run_research(ROOT / "configs/ablations.yaml", 0, tmp_path)
    for folder in ["tables", "figures"]:
        for file in (first / folder).iterdir():
            assert file.read_bytes() == (tmp_path / folder / file.name).read_bytes(), file.name


@pytest.mark.parametrize(
    "prose",
    [
        "Accuracy was 0.9.",
        "Improved by 8 percent.",
        "n=360.",
        "Accuracy was $0.9$.",
        "Accuracy $1$.",
        "$$0.9$$",
    ],
)
def test_untraceable_prose_result_is_rejected(prose):
    source = (ROOT / "docs/paper.src.md").read_text()
    with pytest.raises(ValueError, match="Numeric prose"):
        validate_source(source + "\n" + prose)


def test_paper_placeholders_and_staleness(evidence, tmp_path):
    path, _ = evidence
    source = (ROOT / "docs/paper.src.md").read_text()
    rendered = render(source, path)
    assert "{{" not in rendered and "unrun" in rendered
    destination = tmp_path / "paper.md"
    args = ["--research", str(path), "--output", str(destination)]
    paper_main(args)
    paper_main([*args, "--check"])
    destination.write_text(rendered + "Stale.\n")
    with pytest.raises(SystemExit, match="stale"):
        paper_main([*args, "--check"])
    assert destination.read_text().endswith("Stale.\n")
    with pytest.raises(ValueError, match="Unknown table"):
        render(source + "\n{{table:absent}}", path)


def test_artifact_tampering_is_detected(evidence):
    path, result = evidence
    modified = copy.deepcopy(result["manifest"])
    modified["artifacts"]["tables/dose.json"] = hashlib.sha256(b"changed").hexdigest()
    manifest = path / "manifest.json"
    original = manifest.read_text()
    try:
        manifest.write_text(json.dumps(modified))
        with pytest.raises(ValueError, match="changed evidence"):
            render((ROOT / "docs/paper.src.md").read_text(), path)
    finally:
        manifest.write_text(original)


@pytest.fixture
def research_backend():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import Qwen2Config, Qwen2ForCausalLM

    from nous.model.hf_backend import HFBackend
    from nous.model.tiny_backend import ByteTokenizer

    torch.set_num_threads(1)
    with torch.random.fork_rng():
        torch.manual_seed(4)
        model = Qwen2ForCausalLM(
            Qwen2Config(
                vocab_size=256,
                hidden_size=16,
                intermediate_size=32,
                num_hidden_layers=24,
                num_attention_heads=2,
                num_key_value_heads=2,
                eos_token_id=None,
            )
        ).eval()
    backend = HFBackend.__new__(HFBackend)
    backend.tokenizer = ByteTokenizer()
    backend._configure(model)
    backend.probe_layers = set(range(24))
    return backend


def test_capture_all_requested_layers_excludes_prefill_sink(research_backend):
    from nous.research.capture import CaptureBackend, uninjected

    backend = research_backend
    capture = CaptureBackend(backend)
    text, layers = uninjected(capture, "tea", 0, tokens=3)
    assert text and len(capture.states) == 3
    assert set(layers) == set(range(24))
    assert all(array.shape == (3, 16) for array in layers.values())
    assert all(state.position > 3 and state.cache is None for state in capture.states)
    assert all(not block._forward_hooks for block in backend.model.model.layers)


def test_research_generator_zero_control_and_larger_dose(research_backend):
    from nous.concepts.library import Concept, ConceptLibrary
    from nous.research.capture import CaptureBackend, answer, uninjected

    backend = research_backend
    capture = CaptureBackend(backend)
    rng = np.random.default_rng(8)
    directions = rng.normal(size=(3, 16))
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    library = ConceptLibrary(
        [Concept(f"test{i}", f"Test {i}", i, ()) for i in range(3)],
        directions,
        directions.copy(),
        np.zeros(16),
        np.full(3, 0.1),
        {
            "model": "TINY MODEL / CI",
            "variant": "others",
            "injection_layer": 16,
            "readout_layer": 20,
            "probe_layers": [16, 20, 22],
            "median_residual_norm": 26.78,
        },
        np.zeros(3),
        np.ones(3),
        np.full(3, 10.0),
    )
    plain, _ = uninjected(capture, "Explain how to make tea.", 0)
    baseline_states = capture.states.copy()
    control, off_states = answer(capture, library, "test0", "Explain how to make tea.", 0, 0, False)
    assert control and plain
    # Presentation can omit an incomplete byte tail; the model states must still match.
    assert len(off_states) == len(baseline_states)
    for before, after in zip(baseline_states, off_states, strict=True):
        np.testing.assert_array_equal(before.layer_hidden[20], after.layer_hidden[20])
    injected, on_states = answer(
        capture, library, "test0", "Explain how to make tea.", 0, 1.5, False
    )
    assert injected and len(on_states) > 0
    assert not np.allclose(off_states[0].layer_hidden[16], on_states[0].layer_hidden[16])
    _, defended = answer(capture, library, "test0", "Explain how to make tea.", 0, 0.45, True)
    assert any(np.max(s.defence_pre - s.defence_post) > 0 for s in defended)
