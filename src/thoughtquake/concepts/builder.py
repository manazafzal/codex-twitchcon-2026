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


def build_legacy_library(
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


def git_revision() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def trace_answer(
    backend: ModelBackend, prompt: str, rng: np.random.Generator, max_tokens: int = 32
) -> tuple[str, dict[int, Vector], Vector]:
    state = backend.prefill(prompt)
    tokens: list[int] = []
    layers = {backend.injection_layer, backend.readout_layer, min(22, backend.num_layers - 1)}
    hidden: dict[int, list[Vector]] = {layer: [] for layer in layers}
    defence: list[Vector] = []
    for _ in range(max_tokens):
        token = backend.sample(state.logits, 0.8, 0.95, rng)
        if token == backend.eos_token_id:
            break
        tokens.append(token)
        _, _, state = backend.step(state, token)
        for layer in layers:
            hidden[layer].append(state.layer_hidden.get(layer, state.readout_hidden).copy())
        if state.defender_hidden is not None:
            defence.append(state.defender_hidden.copy())
    if not tokens or not defence:
        raise ValueError("Generation produced no usable positions")
    return (
        backend.decode(tokens),
        {layer: np.stack(values) for layer, values in hidden.items()},
        np.stack(defence),
    )


def neutral_set(
    backend: ModelBackend, count: int, seed: int
) -> list[tuple[str, dict[int, Vector], Vector]]:
    from thoughtquake.engine.generate import PROMPTS

    rng = np.random.default_rng(seed)
    return [trace_answer(backend, PROMPTS[10 + i % 30], rng) for i in range(count)]


def build_library(
    backend: ModelBackend,
    concepts: list[Concept],
    *,
    seed: int = 0,
    samples: int = 8,
    neutral_samples: int = 60,
    model_id: str = "TINY MODEL / CI",
    variant: str = "others",
    median_norm: float | None = None,
) -> ConceptLibrary:
    from thoughtquake.concepts.probe import text_hash

    if variant == "neutral":
        return build_legacy_library(
            backend,
            concepts,
            seed=seed,
            samples=samples,
            neutral_samples=neutral_samples,
            model_id=model_id,
        )
    if variant != "others" or len(concepts) < 2 or samples < 1 or neutral_samples < 60:
        raise ValueError(
            "The others variant needs at least two concepts and 60 neutral generations"
        )
    rng = np.random.default_rng(seed)
    sets = [
        [
            trace_answer(backend, f"Write one short vivid sentence about {c.label}.", rng)
            for _ in range(samples)
        ]
        for c in concepts
    ]

    def directions(layer: int) -> Vector:
        means = np.stack(
            [np.concatenate([row[1][layer] for row in group]).mean(axis=0) for group in sets]
        )
        others = (means.sum(axis=0) - means) / (len(concepts) - 1)
        return unit(means - others)

    V, D = directions(backend.injection_layer), directions(backend.readout_layer)
    calibration_seed = seed if seed != 1 else 2
    neutral = neutral_set(backend, neutral_samples, calibration_seed)
    positions = np.concatenate([row[1][backend.readout_layer] for row in neutral])
    projections = unit(positions) @ D.T
    defence = np.concatenate([row[2] for row in neutral])
    residual = np.concatenate([row[1][backend.injection_layer] for row in neutral])
    config = {
        "model": model_id,
        "variant": variant,
        "seed": seed,
        "seeds": [seed, calibration_seed],
        "samples": samples,
        "neutral_samples": neutral_samples,
        "injection_layer": backend.injection_layer,
        "readout_layer": backend.readout_layer,
        "probe_layers": sorted(
            {backend.injection_layer, backend.readout_layer, min(22, backend.num_layers - 1)}
        ),
        "defender_layer": backend.injection_layer + 1,
        "hidden_size": backend.hidden_size,
        "median_residual_norm": median_norm
        if median_norm is not None
        else float(np.median(np.linalg.norm(residual, axis=1))),
        "median_norm_source": "configured reference"
        if median_norm is not None
        else "neutral positions",
        "excluded_positions": [0],
        "readout_calibration_seed": calibration_seed,
    }
    texts = [row[0] for group in sets for row in group] + [row[0] for row in neutral]
    library = ConceptLibrary(
        concepts,
        V,
        D,
        np.zeros(backend.hidden_size),
        np.percentile(defence @ V.T, 97, axis=0),
        config,
        projections.mean(axis=0),
        np.maximum(projections.std(axis=0), 1e-6),
        provenance={
            "git_hash": git_revision(),
            "texts_hash": config_hash_texts(texts),
            "calibration_text_hashes": [text_hash(row[0]) for row in neutral],
        },
    )
    calibrate_alarm(backend, library, count=neutral_samples, seed=1)
    return library


def config_hash_texts(texts: list[str]) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()


def calibrate_alarm(
    backend: ModelBackend, library: ConceptLibrary, *, count: int = 60, seed: int = 1
) -> None:
    from thoughtquake.concepts.probe import text_hash

    if count < 60 or seed == library.config.get("readout_calibration_seed"):
        raise ValueError("Alarm calibration needs at least 60 generations with a fresh seed")
    fresh = neutral_set(backend, count, seed)
    old = set(library.provenance.get("calibration_text_hashes", []))
    if old & {text_hash(row[0]) for row in fresh}:
        raise ValueError("Alarm generations overlap the readout calibration texts")
    positions = np.concatenate([row[2] for row in fresh])
    library.alarm_thresholds = np.percentile(positions @ unit(library.V).T, 99.5, axis=0)
    library.config.update(alarm_seed=seed, alarm_generations=count)
    library.provenance["alarm_texts_hash"] = config_hash_texts([row[0] for row in fresh])
