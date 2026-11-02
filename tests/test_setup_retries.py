"""Intermittent refusals and repeated answers must not break first-run generation."""

import json

import numpy as np
import pytest
from test_concept_builder import TopicModel

from nous.cli import main
from nous.concepts import builder
from nous.concepts.library import ConceptLibrary
from nous.concepts.probe import check_partitions, text_hash
from nous.concepts.sampling import MAX_ATTEMPTS, replacement
from nous.server.session import mock_library

REFUSAL = "I'm sorry, but I can't assist with that."
REPEATED = "A calm routine at home keeps the tea warm."


class RefusingModel(TopicModel):
    def __init__(self):
        super().__init__()
        self.generations = 0
        self.tokens[-1], self.tokens[-2] = REFUSAL, REPEATED

    def prefill(self, *args, **kwargs):
        self.generations += 1
        return super().prefill(*args, **kwargs)

    def sample(self, logits, temperature, top_p, rng):
        if logits[1]:
            return 0
        if self.generations % 4 in {1, 2}:
            return -1
        if self.generations % 4 == 3:
            return -2
        return super().sample(logits, temperature, top_p, rng)


def test_build_and_fit_commands_replace_refusals_and_duplicates(monkeypatch, tmp_path):
    import nous.model.hf_backend as hf
    from nous import cli

    backends = []
    captured = {}
    original_neutral = builder.neutral_set

    def backend(**kwargs):
        model = RefusingModel()
        backends.append(model)
        return model

    def neutral(backend, count, seed, **kwargs):
        rows = original_neutral(backend, count, seed, **kwargs)
        captured[seed] = [text_hash(row[0]) for row in rows]
        return rows

    monkeypatch.setattr(hf, "HFBackend", backend)
    monkeypatch.setattr(cli, "load_concepts", lambda: mock_library(all_concepts=False).concepts)
    monkeypatch.setattr(builder, "neutral_set", neutral)
    monkeypatch.setenv("NOUS_MODEL", "TINY MODEL / CI")
    path = tmp_path / "library.npz"
    main(["build-library", "--seed", "0", "--samples", "2", "--output", str(path)])
    ConceptLibrary.load(path)
    assert len(captured[0]) == len(set(captured[0])) == 60
    assert len(captured[1]) == len(set(captured[1])) == 60
    assert not set(captured[0]) & set(captured[1])
    assert text_hash(REFUSAL) not in {*captured[0], *captured[1]}
    assert backends[0].generations > 126
    main(["fit-readout", "--library", str(path)])
    fitted = ConceptLibrary.load(path)
    assert fitted.readout_v4["weights"].shape == (3, 64)
    partitions = fitted.provenance["readout_v4"]["partitions"]
    assert {key: part["n"] for key, part in partitions.items()} == {
        "train": 198,
        "validation": 6,
        "test": 36,
    }
    hashes = [part["text_hashes"] for part in partitions.values()]
    assert len({h for part in hashes for h in part}) == sum(map(len, hashes))
    assert all(text_hash(REFUSAL) not in group for group in hashes)
    assert json.loads(path.with_suffix(".fit.json").read_text())["source"] == "mock"


def test_permanent_refusal_fails_bounded_without_fabricating_a_replacement():
    calls = []

    def refuse(attempt):
        calls.append(attempt)
        return REFUSAL, REFUSAL

    with pytest.raises(ValueError, match="bounded retries"):
        replacement(refuse, set())
    assert len(calls) == MAX_ATTEMPTS


def test_overlap_guard_still_rejects_external_leaks():
    from nous.concepts.probe import Example

    def row(text, family, seed):
        return Example(text, "ocean", family, seed, np.ones(2))

    with pytest.raises(ValueError, match="overlap"):
        check_partitions(
            [row("same answer", "train", 1)],
            [row(" SAME ANSWER ", "validation", 2)],
            [row("different", "test", 3)],
        )


def test_alarm_overlap_guard_still_rejects_a_faulty_generator(monkeypatch):
    library = mock_library(all_concepts=False)
    library.config["readout_calibration_seed"] = 0
    library.provenance["calibration_text_hashes"] = [text_hash("shared answer")]

    def faulty(backend, count, seed, **kwargs):
        return [("shared answer", {}, np.ones((1, 32))) for _ in range(count)]

    monkeypatch.setattr(builder, "neutral_set", faulty)
    with pytest.raises(ValueError, match="overlap"):
        builder.calibrate_alarm(RefusingModel(), library, seed=1)


def test_saved_fit_contains_idle_margin_calibration(monkeypatch, tmp_path):
    import nous.model.hf_backend as hf

    monkeypatch.setattr(hf, "HFBackend", lambda **kwargs: RefusingModel())
    library = mock_library(all_concepts=False)
    library.config.update(probe_layers=[7, 11], injection_layer=7, readout_layer=11)
    path = tmp_path / "library.npz"
    library.save(path)
    main(["fit-readout", "--library", str(path)])
    fitted = ConceptLibrary.load(path)
    calibration = fitted.provenance["readout_v4"]["margin_calibration"]
    assert calibration["status"] == "calibrated" and calibration["idle_n"] == 60
    assert len(set(calibration["text_hashes"])) == 60
    assert text_hash(REFUSAL) not in calibration["text_hashes"]
    cutoff = fitted.config["readout_v4_margin_threshold"]
    main(["fit-readout", "--library", str(path), "--data", str(tmp_path / "readout-training.npz")])
    assert ConceptLibrary.load(path).config["readout_v4_margin_threshold"] == cutoff
