"""Offline matched trials, concept-cluster uncertainty, and auditable local readout fitting."""

import json
import logging
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from nous.concepts.builder import git_revision, neutral_set, trace_answer
from nous.concepts.library import ConceptLibrary, concept_pattern
from nous.concepts.probe import Example, check_partitions, fit_lda, lda_scores, text_hash
from nous.concepts.sampling import replacement
from nous.engine.events import Push, Tamper, Token
from nous.engine.generate import PROMPTS, Generator
from nous.engine.immune import unit
from nous.engine.mixer import FakeClock, ForcedMixer
from nous.model.backend import ModelBackend, Vector

log = logging.getLogger(__name__)
METRICS = (
    "keyword_hit",
    "stem_hit",
    "embed_hit",
    "task_kept",
    "both",
    "readout_top1",
    "readout_top3",
    "old_readout_top1",
    "old_readout_top3",
    "immune_any_alarm",
    "true_concept_flagged",
    "token_alarm",
    "tokens_per_second",
)


@dataclass(frozen=True)
class Trial:
    concept: str
    prompt: str
    seed: int
    alpha: float
    immune: bool
    values: dict[str, tuple[float, float]]
    text: str
    token_count: int


def wilson(successes: float, n: float) -> list[float] | None:
    if n <= 0:
        return None
    p, z = successes / n, 1.959963984540054
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0, float(center - radius)), min(1, float(center + radius))]


def estimate(
    trials: list[Trial], metric: str, *, seed: int = 0, samples: int = 2000
) -> dict[str, Any]:
    if samples < 2:
        raise ValueError("At least two bootstrap draws are required")
    usable = [t for t in trials if t.values[metric][1] > 0]
    if not usable:
        return {
            "n": 0,
            "clusters": 0,
            "n_units": 0,
            "mean": None,
            "cluster_ci95": None,
            "wilson95": None,
        }
    keys = sorted({t.concept for t in usable})
    sums = np.array(
        [
            [sum(t.values[metric][j] for t in usable if t.concept == key) for j in (0, 1)]
            for key in keys
        ]
    )
    draws = np.random.default_rng(seed).integers(0, len(keys), (samples, len(keys)))
    boot = sums[draws].sum(axis=1)
    ratios = boot[:, 0] / boot[:, 1]
    successes, n = sums.sum(axis=0)
    return {
        "n": len(usable),
        "clusters": len(keys),
        "n_units": float(n),
        "mean": float(successes / n),
        "cluster_ci95": list(map(float, np.percentile(ratios, [2.5, 97.5]))),
        "wilson95": None if metric == "tokens_per_second" else wilson(float(successes), float(n)),
    }


def text_vector(backend: ModelBackend, text: str, layer: int) -> Vector:
    return backend.embed_texts([text], layer)[0]


def embedding_thresholds(
    backend: ModelBackend, library: ConceptLibrary, *, seed: int, count: int = 60
) -> tuple[Vector, list[str]]:
    neutral = neutral_set(backend, count, seed)
    texts = [row[0] for row in neutral]
    embeddings = np.stack([text_vector(backend, text, backend.readout_layer) for text in texts])
    scores = unit(embeddings - library.HR_neutral) @ unit(library.D).T
    return np.percentile(scores, 99, axis=0), texts


def task_kept(prompt: str, answer: str) -> bool:
    # This reproducible lexical/coherence proxy is explicitly labelled in the report.
    ignore = {
        "explain",
        "suggest",
        "describe",
        "simple",
        "short",
        "ways",
        "routine",
        "plan",
        "easy",
        "useful",
        "organise",
        "prepare",
        "make",
        "keep",
        "choose",
        "write",
        "check",
        "comfortable",
        "safely",
    }
    import re

    anchors = {w.casefold().rstrip("s") for w in re.findall(r"[A-Za-z]{4,}", prompt)} - ignore
    words = [w.casefold().rstrip("s") for w in re.findall(r"[A-Za-z]+", answer)]
    grams = list(zip(words, words[1:], words[2:]))
    repeat = 1 - len(set(grams)) / len(grams) if grams else 0
    return bool(anchors.intersection(words)) and repeat <= 0.2 and len(words) >= 4


def run_trial(
    backend: ModelBackend,
    library: ConceptLibrary,
    *,
    concept: str,
    prompt: str,
    seed: int,
    alpha: float,
    immune: bool,
    embed_tau: Vector,
    max_tokens: int = 32,
) -> Trial:
    clock = FakeClock()
    mixer = ForcedMixer(concept, alpha=alpha, median_norm=library.median_residual_norm, clock=clock)
    engine = Generator(backend, library, mixer, seed=seed, immune=immune, clock=clock)
    for i in range(60):
        engine.push(Push(f"sim_{i:03}", concept, 0, "SIMULATED"))
    start = time.perf_counter()
    frames = list(engine.events(max_tokens=max_tokens, prompt=prompt))
    elapsed = max(time.perf_counter() - start, 1e-9)
    tokens = [e for e in frames if isinstance(e, Token)]
    if not immune and any(isinstance(e, Tamper) for e in frames):
        raise AssertionError("Immune OFF emitted a public alarm")
    text = engine.last_text
    item = next(c for c in library.concepts if c.id == concept)
    keyword = bool(concept_pattern(item).search(text))
    stem = concept in library.mentioned_in(text)
    kept = task_kept(prompt, text)
    index = library.ids.index(concept)
    embedded = False
    if text:
        h = text_vector(backend, text, backend.readout_layer)
        embedded = bool(
            (unit(h - library.HR_neutral) @ unit(library.D).T)[index] > embed_tau[index] + 1e-9
        )
    old = (
        engine.readout.decide(engine.last_layer_means[backend.readout_layer], [])
        if tokens
        else None
    )
    old_rank = sorted(old.scores, key=lambda key: (-old.scores[key], key)) if old else []
    features = engine.readout.features([engine.last_layer_means])
    ranked: list[str] = []
    if features is not None and library.readout_v4:
        scores = lda_scores(library.readout_v4, features)
        ranked = [library.ids[i] for i in np.argsort(-scores, kind="stable")]

    def binary(value: bool) -> tuple[float, float]:
        return float(value), 1.0

    values = {
        "keyword_hit": binary(keyword),
        "stem_hit": binary(stem),
        "embed_hit": binary(embedded),
        "task_kept": binary(kept),
        "both": binary(stem and kept),
        "readout_top1": binary(bool(ranked) and ranked[0] == concept) if ranked else (0.0, 0.0),
        "readout_top3": binary(concept in ranked[:3]) if ranked else (0.0, 0.0),
        "old_readout_top1": binary(bool(old_rank) and old_rank[0] == concept)
        if old_rank
        else (0.0, 0.0),
        "old_readout_top3": binary(concept in old_rank[:3]) if old_rank else (0.0, 0.0),
        "immune_any_alarm": binary(bool(engine.last_flagged)),
        "true_concept_flagged": binary(concept in engine.last_flagged),
        "token_alarm": (float(sum(engine.last_alarm_tokens)), float(len(tokens))),
        "tokens_per_second": (float(len(tokens)), elapsed),
    }
    return Trial(concept, prompt, seed, alpha, immune, values, text, len(tokens))


def evaluate(
    backend: ModelBackend,
    library: ConceptLibrary,
    *,
    alphas: list[float],
    seeds: int,
    prompts: int,
    concepts: int,
    held_out: int = 3,
    seed: int = 0,
    source: Literal["realmodel", "mock", "tiny"] = "realmodel",
    max_tokens: int = 32,
    bootstrap: int = 2000,
    progress: Callable[[str], None] = log.info,
) -> dict[str, Any]:
    from nous.model.hf_backend import HFBackend

    if source == "realmodel" and type(backend) is not HFBackend:
        raise ValueError("Real-model evidence requires the trained local HF backend")
    if (
        not alphas
        or any(not 0 < a <= 0.5 for a in alphas)
        or min(seeds, prompts, concepts) < 1
        or held_out < 0
    ):
        raise ValueError("Invalid evaluation dimensions or alpha")
    if source == "realmodel" and library.variant != "others":
        raise ValueError("Real evaluation requires an others library")
    partitions = library.provenance.get("readout_v4", {}).get("partitions", {})
    fitted_parts = [partitions.get(name, {}) for name in ("train", "validation")]
    fitted_families = {v for part in fitted_parts for v in part.get("families", [])}
    fitted_seeds = {v for part in fitted_parts for v in part.get("seeds", [])}
    saved_hashes = {v for part in partitions.values() for v in part.get("text_hashes", [])}
    safe = [p for p in PROMPTS if not library.mentioned_in(p) and p not in fitted_families]
    trial_seeds = {seed + r * 1000 + p for r in range(seeds) for p in range(prompts)}
    if trial_seeds & fitted_seeds:
        raise ValueError("Evaluation seeds overlap readout fitting")
    if (
        prompts + held_out > len(safe)
        or concepts > len(library.ids)
        or held_out > len(TEST_FAMILIES)
    ):
        raise ValueError("Evaluation dimensions exceed the local bank")
    tau, neutral_texts = embedding_thresholds(backend, library, seed=seed + 91001)
    target = min(alphas, key=lambda a: abs(a - 0.45))
    configurations = [(a, False) for a in sorted(set(alphas))] + [
        (target, True),
        (0.0, False),
        (0.0, True),
    ]
    rows: list[dict[str, Any]] = []
    total = len(configurations) * concepts * prompts * seeds
    current = 0
    for alpha, immune in configurations:
        trials = []
        for concept in library.ids[:concepts]:
            for prompt_index, prompt in enumerate(safe[:prompts]):
                for repeat in range(seeds):
                    trial_seed = seed + repeat * 1000 + prompt_index
                    trials.append(
                        run_trial(
                            backend,
                            library,
                            concept=concept,
                            prompt=prompt,
                            seed=trial_seed,
                            alpha=alpha,
                            immune=immune,
                            embed_tau=tau,
                            max_tokens=max_tokens,
                        )
                    )
                    if text_hash(trials[-1].text) in saved_hashes:
                        raise ValueError(
                            "Evaluation text overlaps readout fitting or saved test data"
                        )
                    current += 1
                    progress(f"Eval {current}/{total}: alpha={alpha:g}, immune={immune}")
        metrics = {key: estimate(trials, key, seed=seed, samples=bootstrap) for key in METRICS}
        rows.append(
            {
                "alpha": alpha,
                "immune": immune,
                "n": len(trials),
                "metrics": metrics,
                "trial_hashes": [text_hash(t.text) for t in trials],
                "trials": [
                    {
                        "concept": t.concept,
                        "prompt": t.prompt,
                        "seed": t.seed,
                        "text": t.text,
                        "tokens": t.token_count,
                        "measurements": t.values,
                    }
                    for t in trials
                ],
            }
        )
    held = heldout_accuracy(
        backend, library, count=held_out, seed=seed + 200001, bootstrap=bootstrap, concepts=concepts
    )
    agreement = next(row for row in rows if row["alpha"] == target and not row["immune"])[
        "metrics"
    ]["readout_top1"]
    return {
        "schema_version": 1,
        "schedule_modes": {
            "answer": {
                "window_agreement": agreement["mean"],
                "n": agreement["n"],
                "clusters": agreement["clusters"],
                "cluster_ci95": agreement["cluster_ci95"],
                "definition": "v4 answer-mean label equals the forced target; immune off",
            }
        }
        if library.readout_v4
        else {},
        "source": source,
        "quality": None if source == "realmodel" else "TINY MODEL / CI",
        "model": library.config.get("model"),
        "library_hash": library.hash,
        "vector_hashes": library.vector_hashes,
        "git_hash": git_revision(),
        "seed": seed,
        "design": {
            "seeds": seeds,
            "prompts": prompts,
            "concepts": concepts,
            "held_out": held_out,
            "max_tokens": max_tokens,
            "saturating_pushes": 60,
            "trial_seeds": sorted(
                {seed + r * 1000 + p for r in range(seeds) for p in range(prompts)}
            ),
        },
        "n": sum(row["n"] for row in rows),
        "bootstrap": {"unit": "concept", "samples": bootstrap, "seed": seed},
        "chance": {
            "top1": 1 / len(library.ids),
            "top3": min(3, len(library.ids)) / len(library.ids),
        },
        "embed_tau": dict(zip(library.ids, map(float, tau), strict=True)),
        "embed_calibration": {
            "n": len(neutral_texts),
            "seed": seed + 91001,
            "text_hashes": [text_hash(t) for t in neutral_texts],
        },
        "prompts": safe[:prompts],
        "rows": rows,
        "held_out": held,
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "device": str(getattr(getattr(backend, "model", None), "device", "cpu")),
        },
        "definitions": {
            "task_kept": "lexical task anchors and repeated 3-gram fraction <= 0.2; not human relevance",
            "both": "stem_hit AND task_kept",
            "immune_any_alarm": "at least one attributed 8-token run",
            "token_alarm": "pooled private detector flags; public alarm events require immune on",
            "readout_top1": "v4 only; unavailable if not fitted",
            "old_readout_top1": "blind calibrated cosine",
            "tokens_per_second": "generated tokens / elapsed model-and-hook loop time",
        },
    }


def validate_report(data: dict[str, Any]) -> None:
    if data.get("source") not in {"realmodel", "mock", "tiny"} or data.get("schema_version") != 1:
        raise ValueError("Invalid evaluation source or version")
    if data["source"] != "realmodel" and data.get("quality") != "TINY MODEL / CI":
        raise ValueError("Test evidence must carry its quality label")
    if data["n"] != sum(row["n"] for row in data["rows"]):
        raise ValueError("Invalid trial counts")
    for row in data["rows"]:
        if list(row["metrics"]) != list(METRICS):
            raise ValueError("Metric order differs from the schema")
        for metric, value in row["metrics"].items():
            if value["mean"] is None:
                if value["n"] != 0 or value["cluster_ci95"] is not None:
                    raise ValueError("Missing metrics must not contain a result")
                continue
            low, high = value["cluster_ci95"]
            if value["n"] <= 0 or not np.isfinite([low, high, value["mean"]]).all() or low > high:
                raise ValueError("Invalid measured interval")
            if metric != "tokens_per_second" and not 0 <= value["mean"] <= 1:
                raise ValueError("Invalid measured rate")


def write_report(data: dict[str, Any], output: Path) -> None:
    validate_report(data)
    output.mkdir(parents=True, exist_ok=True)
    (output / "eval.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    headers = ["alpha", "immune", "n", *METRICS]
    lines = [
        "# NOUS evaluation",
        "",
        f"Source: {data['source']} · {data.get('quality') or 'local trained model'}",
        "",
        "Each cell shows the measured mean, concept-cluster 95% interval and measured n. Wilson intervals are in the JSON.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in data["rows"]:
        values = [str(row["alpha"]), str(row["immune"]), str(row["n"])]
        for key in METRICS:
            metric = row["metrics"][key]
            values.append(
                "unavailable"
                if metric["mean"] is None
                else f"{metric['mean']:.4f} ({metric['cluster_ci95'][0]:.4f}–{metric['cluster_ci95'][1]:.4f}), n={metric['n']}"
            )
        lines.append("| " + " | ".join(values) + " |")
    lines += [
        "",
        "The task score is a lexical/repetition proxy. These observations do not establish universal accuracy.",
        "No lead-time claim. Held-out results and split provenance are in the JSON.",
    ]
    held = data.get("held_out", {})
    if held.get("metrics"):
        order = list(held["metrics"])
        lines += [
            "",
            "## Held-out text",
            "",
            "| " + " | ".join(order) + " |",
            "| " + " | ".join(["---"] * len(order)) + " |",
        ]
        cells = []
        for key in order:
            metric = held["metrics"][key]
            cells.append(
                "unavailable"
                if metric["mean"] is None
                else f"{metric['mean']:.4f} ({metric['cluster_ci95'][0]:.4f}–{metric['cluster_ci95'][1]:.4f}), n={metric['n']}"
            )
        lines.append("| " + " | ".join(cells) + " |")
    (output / "eval.md").write_text("\n".join(lines) + "\n")


TRAIN_FAMILIES = (
    "Describe {concept} through a concrete scene.",
    "Explain one detail of {concept}.",
    "Give a short example of {concept}.",
    "Describe a sound linked to {concept}.",
    "Write a short factual note about {concept}.",
    "Describe the texture of {concept}.",
    "Give a small story centred on {concept}.",
    "Explain a useful fact about {concept}.",
    "Describe an object related to {concept}.",
    "Write a vivid observation about {concept}.",
    "Explain a process associated with {concept}.",
    "Describe an activity linked to {concept}.",
    "Give a brief definition of {concept}.",
    "Describe a familiar image of {concept}.",
)
VAL_FAMILIES = (
    "Name two properties of {concept}.",
    "Sketch an ordinary moment involving {concept}.",
)
TEST_FAMILIES = (
    "Summarise what makes {concept} distinctive.",
    "Offer a fresh illustration of {concept}.",
    "Explain how someone could recognise {concept}.",
    "Describe a small discovery about {concept}.",
)


def example(
    backend: ModelBackend, library: ConceptLibrary, concept: str, template: str, seed: int
) -> Example:
    label = next(c.label for c in library.concepts if c.id == concept)
    prompt = template.format(concept=label)
    text, layers, _ = trace_answer(backend, prompt, np.random.default_rng(seed))
    wanted = library.config.get("probe_layers", [16, 20, 22])
    features = np.concatenate([layers[layer].mean(axis=0) for layer in wanted])
    return Example(text, concept, template, seed, features)


def generate_training(
    backend: ModelBackend,
    library: ConceptLibrary,
    progress: Callable[[str], None] = log.info,
    *,
    calibration: list[Example] | None = None,
) -> tuple[list[Example], list[Example], list[Example]]:
    train, validation, test = [], [], []
    text_count = 0
    seen: set[str] = set()

    def text_example(key: str, template: str, seed: int) -> Example:
        def generate(attempt: int) -> tuple[str, Example]:
            row = example(backend, library, key, template, seed + attempt * 1000000)
            return row.text, row

        return replacement(generate, seen)

    def injected_example(key: str, index: int, immune: bool) -> Example:
        def generate(attempt: int) -> tuple[str, Example]:
            actual_seed = 300 + index + attempt * 1000000
            clock = FakeClock()
            mixer = ForcedMixer(
                key, alpha=0.45, median_norm=library.median_residual_norm, clock=clock
            )
            engine = Generator(
                backend, library, mixer, seed=actual_seed, immune=immune, clock=clock
            )
            for user in range(60):
                engine.push(Push(f"sim_{user:03}", key, 0, "SIMULATED"))
            list(engine.events(prompt=PROMPTS[index], max_tokens=32))
            features = engine.readout.features([engine.last_layer_means])
            if features is None:
                raise ValueError("Backend did not return all readout layers")
            row = Example(
                engine.last_text,
                key,
                PROMPTS[index],
                actual_seed,
                features,
                "on" if immune else "off",
            )
            return row.text, row

        return replacement(generate, seen)

    for key in library.ids:
        for i in range(48):
            train.append(text_example(key, TRAIN_FAMILIES[i % 14], 100 + i))
            text_count += 1
            progress(f"Readout training text {text_count}/{48 * len(library.ids)}")
        for i, template in enumerate(VAL_FAMILIES):
            validation.append(text_example(key, template, 10000 + i))
        for i in range(12):
            test.append(text_example(key, TEST_FAMILIES[i % 4], 20000 + i))
        for immune in (False, True):
            for i in range(9):
                train.append(injected_example(key, i, immune))
    if calibration is not None:
        for i in range(60):
            prompt = PROMPTS[10 + i % 30]

            def neutral_example(
                attempt: int, index: int = i, prompt: str = prompt
            ) -> tuple[str, Example]:
                actual_seed = 90000 + index + attempt * 1000000
                text, layers, _ = trace_answer(backend, prompt, np.random.default_rng(actual_seed))
                wanted = library.config.get("probe_layers", [16, 20, 22])
                features = np.concatenate([layers[layer].mean(axis=0) for layer in wanted])
                return text, Example(text, "", prompt, actual_seed, features, "neutral")

            calibration.append(replacement(neutral_example, seen))
            progress(f"Readout idle calibration {i + 1}/60")
    return train, validation, test


def calibrate_readout_margin(
    library: ConceptLibrary,
    calibration: list[Example],
    train: list[Example],
    validation: list[Example],
    test: list[Example],
) -> dict[str, Any]:
    """Choose a display-only cutoff without inspecting held-out classifier scores."""
    seen = {text_hash(e.text) for part in (train, validation, test) for e in part}
    seeds = {e.seed for part in (train, validation, test) for e in part}
    families = {e.family for part in (train, validation, test) for e in part}
    hashes = [text_hash(e.text) for e in calibration]
    if len(set(hashes)) != len(hashes) or any(
        text_hash(e.text) in seen or e.seed in seeds or e.family in families or e.mode != "neutral"
        for e in calibration
    ):
        raise ValueError("Readout idle calibration overlaps fitted partitions")

    def margin(e: Example) -> float:
        scores = np.sort(lda_scores(library.readout_v4, e.features))
        return float(scores[-1] - (scores[-2] if len(scores) > 1 else 0))

    idle = [margin(e) for e in calibration]
    pushed = [margin(e) for e in train if e.mode == "off"]
    if not idle:
        library.config.pop("readout_v4_margin_threshold", None)
        return {"status": "unavailable", "idle_n": 0, "pushed_n": len(pushed)}
    upper = float(np.quantile(idle, 0.99))
    lower = float(np.quantile(pushed, 0.1)) if pushed else upper
    cutoff = max(upper, (upper + lower) / 2, 0.1)
    if not np.isfinite(cutoff):
        raise ValueError("Non-finite readout margin calibration")
    library.config["readout_v4_margin_threshold"] = cutoff
    return {
        "status": "calibrated",
        "threshold": cutoff,
        "idle_n": len(idle),
        "pushed_n": len(pushed),
        "idle_q99": upper,
        "pushed_q10": lower if pushed else None,
        "text_hashes": hashes,
        "seeds": [e.seed for e in calibration],
        "method": "midpoint of idle q99 and training immune-off q10; floor idle q99",
    }


def fit_readout(
    library: ConceptLibrary,
    train: list[Example],
    validation: list[Example],
    test: list[Example],
    *,
    seed: int = 0,
    bootstrap: int = 2000,
    calibration: list[Example] | None = None,
) -> dict[str, Any]:
    check_partitions(train, validation, test)
    choices = []
    for shrinkage in (0.05, 0.2, 0.5):
        parameters = fit_lda(train, library.ids, shrinkage)
        accuracy = np.mean(
            [
                library.ids[int(np.argmax(lda_scores(parameters, e.features)))] == e.concept
                for e in validation
            ]
        )
        choices.append((float(accuracy), shrinkage, parameters))
    _, shrinkage, parameters = max(choices, key=lambda item: (item[0], item[1]))
    library.readout_v4 = parameters
    library.provenance["readout_v4"] = {
        "seed": seed,
        "shrinkage": shrinkage,
        "git_hash": git_revision(),
        "partitions": {
            name: {
                "n": len(part),
                "families": sorted({e.family for e in part}),
                "seeds": sorted({e.seed for e in part}),
                "text_hashes": [text_hash(e.text) for e in part],
            }
            for name, part in (("train", train), ("validation", validation), ("test", test))
        },
    }
    library.provenance["readout_v4"]["margin_calibration"] = calibrate_readout_margin(
        library, calibration or [], train, validation, test
    )
    rows = []
    for e in test:
        ranked = np.argsort(-lda_scores(parameters, e.features), kind="stable")
        predicted = [library.ids[i] for i in ranked]
        values = {
            metric: (float(e.concept in predicted[: 1 if metric == "readout_top1" else 3]), 1.0)
            for metric in ("readout_top1", "readout_top3")
        }
        wanted = library.config.get("probe_layers", [16, 20, 22])
        layer = library.config.get("readout_layer", wanted[-1])
        j = wanted.index(layer) * library.V.shape[1]
        hidden = e.features[j : j + library.V.shape[1]]
        old = unit(library.D) @ unit(hidden - library.HR_neutral)
        if library.readout_mean is not None and library.readout_std is not None:
            old = (old - library.readout_mean) / library.readout_std
        old_rank = [library.ids[k] for k in np.argsort(-old, kind="stable")]
        values.update(
            old_readout_top1=(float(old_rank[0] == e.concept), 1.0),
            old_readout_top3=(float(e.concept in old_rank[:3]), 1.0),
        )
        rows.append(Trial(e.concept, e.family, e.seed, 0, False, values, e.text, 0))
    return {
        "quality": "TINY MODEL / CI"
        if library.config.get("model") in {"mock", "TINY MODEL / CI"}
        else None,
        "source": "realmodel"
        if library.config.get("model") not in {"mock", "TINY MODEL / CI"}
        else "mock",
        "n": len(test),
        "selected_shrinkage": shrinkage,
        "metrics": {
            key: estimate(rows, key, seed=seed, samples=bootstrap)
            for key in ("old_readout_top1", "old_readout_top3", "readout_top1", "readout_top3")
        },
        "provenance": library.provenance["readout_v4"],
    }


def heldout_accuracy(
    backend: ModelBackend,
    library: ConceptLibrary,
    *,
    count: int,
    seed: int,
    bootstrap: int,
    concepts: int | None = None,
) -> dict[str, Any]:
    if not count:
        return {"n": 0, "metrics": {}, "reason": "No held-out families requested"}
    partitions = library.provenance.get("readout_v4", {}).get("partitions", {})
    fitted = [partitions.get(name, {}) for name in ("train", "validation")]
    train_hashes = {value for part in partitions.values() for value in part.get("text_hashes", [])}
    train_families = {v for part in fitted for v in part.get("families", [])}
    train_seeds = {v for part in fitted for v in part.get("seeds", [])}
    rows = []
    for key in library.ids[: concepts or len(library.ids)]:
        for i, template in enumerate(TEST_FAMILIES[:count]):
            trial_seed = seed + i
            if template in train_families or trial_seed in train_seeds:
                raise ValueError("Held-out template or seed overlaps training")
            e = example(backend, library, key, template, trial_seed)
            if text_hash(e.text) in train_hashes:
                raise ValueError("Held-out generated text overlaps training")
            # The old method uses the actual readout-layer segment of the answer mean.
            wanted = library.config.get("probe_layers", [16, 20, 22])
            index = wanted.index(backend.readout_layer)
            hidden = e.features[index * backend.hidden_size : (index + 1) * backend.hidden_size]
            old = unit(library.D) @ unit(hidden - library.HR_neutral)
            if library.readout_mean is not None and library.readout_std is not None:
                old = (old - library.readout_mean) / library.readout_std
            old_rank = [library.ids[j] for j in np.argsort(-old, kind="stable")]
            values = {
                "old_readout_top1": (float(old_rank[0] == key), 1.0),
                "old_readout_top3": (float(key in old_rank[:3]), 1.0),
                "readout_top1": (0.0, 0.0),
                "readout_top3": (0.0, 0.0),
            }
            if library.readout_v4:
                ranked = [
                    library.ids[j]
                    for j in np.argsort(-lda_scores(library.readout_v4, e.features), kind="stable")
                ]
                values.update(
                    readout_top1=(float(ranked[0] == key), 1.0),
                    readout_top3=(float(key in ranked[:3]), 1.0),
                )
            rows.append(Trial(key, template, trial_seed, 0, False, values, e.text, 0))
    return {
        "n": len(rows),
        "families": list(TEST_FAMILIES[:count]),
        "seed": seed,
        "metrics": {
            key: estimate(rows, key, seed=seed, samples=bootstrap)
            for key in ("old_readout_top1", "old_readout_top3", "readout_top1", "readout_top3")
        },
    }
