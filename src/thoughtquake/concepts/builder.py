from typing import Any

import numpy as np

from thoughtquake.concepts.library import Concept, ConceptLibrary
from thoughtquake.engine.immune import unit
from thoughtquake.model.backend import ModelBackend, Vector


def generate_text(
    backend: ModelBackend, prompt: str, rng: np.random.Generator, max_tokens: int = 32
) -> tuple[str, Vector]:
    state = backend.prefill(prompt)
    tokens = []
    neutral_positions = []
    for _ in range(max_tokens):
        token = backend.sample(state.logits, 0.8, 0.95, rng)
        if token == backend.eos_token_id:
            break
        tokens.append(token)
        _, _, state = backend.step(state, token)
        if state.defender_hidden is not None:
            neutral_positions.append(state.defender_hidden)
    positions = np.asarray(neutral_positions).reshape(-1, backend.hidden_size)
    return backend.decode(tokens), positions


def mean_hidden(backend: ModelBackend, texts: list[str], layer: int) -> Vector:
    # Weight every token equally across texts, rather than weighting short and long texts alike.
    token_hidden = getattr(backend, "token_hidden", None)
    if token_hidden is not None:
        return np.concatenate([token_hidden(text, layer) for text in texts]).mean(axis=0)
    return backend.embed_texts(texts, layer).mean(axis=0)


def build_library(
    backend: ModelBackend,
    concepts: list[Concept],
    *,
    seed: int = 0,
    samples: int = 8,
    neutral_samples: int = 12,
    model_id: str = "TINY MODEL / CI",
) -> ConceptLibrary:
    if samples < 1 or neutral_samples < 1:
        raise ValueError("Contrast sets cannot be empty")
    rng = np.random.default_rng(seed)
    neutral = [
        generate_text(backend, "Write one ordinary sentence about a daily task.", rng)
        for _ in range(neutral_samples)
    ]
    texts = [text for text, _ in neutral]
    base_l = mean_hidden(backend, texts, backend.injection_layer)
    base_r = mean_hidden(backend, texts, backend.readout_layer)
    vectors, directions = [], []
    for concept in concepts:
        generated = [
            generate_text(
                backend, f"Write one short vivid sentence that is all about {concept.label}.", rng
            )[0]
            for _ in range(samples)
        ]
        vectors.append(mean_hidden(backend, generated, backend.injection_layer) - base_l)
        directions.append(mean_hidden(backend, generated, backend.readout_layer) - base_r)
    V, D = np.stack(vectors), np.stack(directions)
    positions = np.concatenate([positions for _, positions in neutral])
    if not len(positions):
        raise ValueError("Neutral generation produced no calibration positions")
    thresholds = np.percentile(positions @ unit(V).T, 97, axis=0)
    config: dict[str, Any] = {
        "model": model_id,
        "seed": seed,
        "samples": samples,
        "neutral_samples": neutral_samples,
        "injection_layer": backend.injection_layer,
        "readout_layer": backend.readout_layer,
        "defender_layer": backend.injection_layer + 1,
        "hidden_size": backend.hidden_size,
    }
    token_hidden = getattr(backend, "token_hidden", None)
    neutral_r = (
        np.concatenate([token_hidden(text, backend.readout_layer) for text in texts])
        if token_hidden
        else backend.embed_texts(texts, backend.readout_layer)
    )
    projections = unit(neutral_r - base_r) @ unit(D).T
    return ConceptLibrary(
        concepts,
        V,
        D,
        base_r,
        thresholds,
        config,
        projections.mean(axis=0),
        np.maximum(projections.std(axis=0), 1e-6),
    )
