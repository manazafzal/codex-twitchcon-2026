import numpy as np
import pytest

from nous.concepts.builder import build_library
from nous.concepts.library import ConceptLibrary, config_hash, load_concepts, match_concept
from nous.model.mock_backend import MockBackend


def test_library_roundtrip_and_hash(tmp_path, library):
    path = tmp_path / "nested/lib.npz"
    library.save(path)
    restored = ConceptLibrary.load(path, {"model": "mock"})
    assert restored.hash == library.hash
    assert restored.concepts == library.concepts
    for name in ("V", "D", "HR_neutral", "thresholds"):
        np.testing.assert_array_equal(getattr(restored, name), getattr(library, name))
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    with pytest.raises(ValueError, match="requested config"):
        ConceptLibrary.load(path, {"model": "different"})
    with np.load(path) as data:
        contents = dict(data)
    contents["V"] = contents["V"] + 1
    np.savez(path, **contents)
    with pytest.raises(ValueError, match="content hash"):
        ConceptLibrary.load(path)


def test_concepts_and_matching():
    concepts = load_concepts()
    assert len(concepts) == 30
    assert len({c.id for c in concepts}) == 30
    assert all(len(c.aliases) == 8 for c in concepts)
    assert match_concept("!push SEA", concepts) == "ocean"
    assert match_concept("star then sea", concepts) == "space"
    assert match_concept("research", concepts) is None


def test_builder_is_deterministic_and_uses_97th_percentile():
    class FixtureBackend(MockBackend):
        def step(self, *args, **kwargs):
            logits, hidden, state = super().step(*args, **kwargs)
            from dataclasses import replace

            return logits, hidden, replace(state, defender_hidden=np.full(32, state.position))

        def embed_texts(self, texts, layer):
            # Every generated contrast text is the same in this fixture.
            return np.ones((len(texts), 32)) * layer

    backend = FixtureBackend()
    first = build_library(
        backend, load_concepts()[:2], samples=1, neutral_samples=2, variant="neutral"
    )
    again = build_library(
        backend, load_concepts()[:2], samples=1, neutral_samples=2, variant="neutral"
    )
    assert first.hash == again.hash
    np.testing.assert_allclose(first.V, 0)
    np.testing.assert_allclose(first.thresholds, 0)


def test_builder_difference_of_means_and_neutral_calibration(monkeypatch):
    from nous.concepts import builder

    prompts = []
    count = 0

    def generated(backend, prompt, rng, max_tokens=32):
        nonlocal count
        prompts.append(prompt)
        count += 1
        if "Ocean" in prompt:
            return "ocean-text", np.zeros((1, 2))
        if "Space" in prompt:
            return "space-text", np.zeros((1, 2))
        return "neutral-text", np.array([[count, 2 * count], [count + 1, 2 * count + 1]])

    class Embeddings:
        injection_layer = 2
        readout_layer = 6
        hidden_size = 2

        def embed_texts(self, texts, layer):
            table = {"neutral-text": [1.0, 2.0], "ocean-text": [4.0, 2.0], "space-text": [1.0, 6.0]}
            return np.array([table[t] for t in texts]) * (2 if layer == 6 else 1)

    monkeypatch.setattr(builder, "generate_text", generated)
    library = builder.build_library(
        Embeddings(), load_concepts()[:2], variant="neutral", neutral_samples=12
    )
    assert len(prompts) == 12 + 2 * 8
    np.testing.assert_allclose(library.V, [[3, 0], [0, 4]])
    np.testing.assert_allclose(library.D, [[6, 0], [0, 8]])
    np.testing.assert_allclose(library.HR_neutral, [2, 4])
    neutral_positions = np.concatenate(
        [np.array([[i, 2 * i], [i + 1, 2 * i + 1]]) for i in range(1, 13)]
    )
    np.testing.assert_allclose(library.thresholds, np.percentile(neutral_positions, 97, axis=0))


def test_mean_hidden_weights_tokens_equally():
    from nous.concepts.builder import mean_hidden

    class Embeddings:
        def token_hidden(self, text, layer):
            return np.array([[2.0, 4.0]]) if text == "short" else np.array([[8.0, 4.0]] * 3)

    np.testing.assert_allclose(mean_hidden(Embeddings(), ["short", "long"], 0), [6.5, 4.0])
