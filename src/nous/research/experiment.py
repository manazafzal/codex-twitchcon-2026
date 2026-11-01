"""Real local generations, shared calibration, and matched one-factor conditions."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from nous.concepts.library import ConceptLibrary, concept_pattern, load_concepts
from nous.concepts.probe import check_partitions, text_hash
from nous.engine.generate import PROMPTS
from nous.engine.immune import unit
from nous.evaluation import generate_training, task_kept
from nous.model.hf_backend import HFBackend
from nous.research.alarms import detect
from nous.research.capture import CaptureBackend, answer, uninjected
from nous.research.classifiers import features, fit_variant
from nous.research.design import cell_id
from nous.research.statistics import Key
from nous.research.vectors import construct

log = logging.getLogger(__name__)


class Experiment:
    def __init__(self, backend: HFBackend, config: dict[str, Any], seed: int, output: Path) -> None:
        if backend.num_layers != 24 or backend.hidden_size != 896:
            raise ValueError(
                "Registered model must have twenty-four layers and the expected hidden width"
            )
        backend.probe_layers = set(range(backend.num_layers))
        self.backend, self.capture = backend, CaptureBackend(backend)
        self.config, self.seed, self.output = config, seed, output
        self.concepts = load_concepts()
        if len(self.concepts) != config["concepts"]:
            raise ValueError("Concept catalog differs from the registered sample")
        self.ids = tuple(c.id for c in self.concepts)
        self.trials: dict[str, dict[Key, dict[str, Any]]] = {}
        self.corpus_hashes: dict[str, list[str]] = {}
        self.libraries: dict[tuple[int, int, str], ConceptLibrary] = {}
        self.primary_classifier: Any = None

    def corpus(self) -> None:
        count = self.config["neutral_generations"]
        self.neutral: list[dict[int, Any]] = []
        self.fresh: list[dict[int, Any]] = []
        self.embedding: list[dict[int, Any]] = []
        for name, target, start in (
            ("neutral", self.neutral, 40000),
            ("alarm", self.fresh, 50000),
            ("embedding", self.embedding, 80000),
        ):
            hashes = []
            for i in range(count):
                log.info("%s calibration %s/%s", name, i + 1, count)
                text, layers = uninjected(self.capture, PROMPTS[10 + i % 30], start + i + self.seed)
                hashes.append(text_hash(text))
                target.append(layers)
            self.corpus_hashes[name] = hashes
        groups = list(self.corpus_hashes.values())
        if any(set(a) & set(b) for i, a in enumerate(groups) for b in groups[i + 1 :]):
            raise ValueError("Independent calibration text hashes overlap")
        self.means: dict[int, list[Any]] = {layer: [] for layer in self.backend.probe_layers}
        self.paired_means: dict[int, list[Any]] = {layer: [] for layer in self.backend.probe_layers}
        contrast_hashes, paired_hashes = [], []
        templates = [
            "Write one short vivid sentence about {concept}.",
            "Describe an ordinary moment involving {concept}.",
        ]
        for concept in self.concepts:
            blocks, paired_blocks = [], []
            for i in range(self.config["contrast_samples"]):
                template = templates[i % len(templates)]
                seed = 60000 + self.seed + i
                text, layers = uninjected(
                    self.capture, template.format(concept=concept.label), seed
                )
                paired_text, neutral = uninjected(
                    self.capture, template.format(concept="a daily task"), seed
                )
                contrast_hashes.append(text_hash(text))
                paired_hashes.append(text_hash(paired_text))
                blocks.append(layers)
                paired_blocks.append(neutral)
            for layer in self.means:
                self.means[layer].append(np.concatenate([b[layer] for b in blocks]).mean(axis=0))
                self.paired_means[layer].append(
                    np.concatenate([b[layer] for b in paired_blocks]).mean(axis=0)
                )
            log.info("Contrast corpus %s", concept.id)
        self.corpus_hashes.update(contrast=contrast_hashes, paired=paired_hashes)

    def directions(self, layer: int, method: str) -> Any:
        tokens = np.concatenate([item[layer] for item in self.neutral])
        return construct(
            np.stack(self.means[layer]),
            tokens.mean(axis=0),
            np.stack(self.paired_means[layer]),
            np.cov(tokens, rowvar=False),
            method,
            seed=self.seed + layer,
        )

    @staticmethod
    def windows(tokens: Any) -> Any:
        return np.stack([tokens[max(0, i - 11) : i + 1].mean(axis=0) for i in range(len(tokens))])

    def library(self, layer: int = 16, readout: int = 20, method: str = "others") -> ConceptLibrary:
        key = (layer, readout, method)
        if key not in self.libraries:
            v, d = self.directions(layer, method), self.directions(readout, method)
            cos = np.concatenate([unit(self.windows(n[readout])) @ d.T for n in self.neutral])
            pre = np.concatenate([n[layer + 1] for n in self.neutral]) @ v.T
            fresh = np.concatenate([n[layer + 1] for n in self.fresh]) @ v.T
            config = {
                "model": self.config["model"],
                "variant": method,
                "injection_layer": layer,
                "readout_layer": readout,
                "probe_layers": [16, 20, 22],
                "defender_layer": layer + 1,
                "hidden_size": self.backend.hidden_size,
                "median_residual_norm": self.config["median_norm"],
                "excluded_positions": [0],
                "median_norm_source": "registered reference, not a new norm measurement",
                "readout_calibration_seed": 40000 + self.seed,
                "alarm_calibration_seed": 50000 + self.seed,
                "contrast_seed": 60000 + self.seed,
                "embedding_calibration_seed": 80000 + self.seed,
                "calibration_generations": len(self.neutral),
            }
            self.libraries[key] = ConceptLibrary(
                self.concepts,
                v,
                d,
                np.zeros(self.backend.hidden_size),
                np.percentile(pre, 97, axis=0),
                config,
                cos.mean(axis=0),
                np.maximum(cos.std(axis=0), 1e-6),
                np.percentile(fresh, 99.5, axis=0),
                provenance={"text_hashes": self.corpus_hashes},
            )
        return self.libraries[key]

    def generation(self, cell: dict[str, Any]) -> dict[Key, dict[str, Any]]:
        identifier = cell_id(cell)
        if identifier in self.trials:
            return self.trials[identifier]
        layer, readout, method = cell["layer"], cell["readout"], cell["vector"]
        self.backend.injection_layer, self.backend.readout_layer = layer, readout
        library = self.library(layer, readout, method)
        assert library.readout_mean is not None and library.readout_std is not None
        assert library.alarm_thresholds is not None
        prompts = [p for p in PROMPTS if not library.mentioned_in(p)][:6]
        if len(prompts) != 6:
            raise ValueError("Not enough registered non-topical prompts")
        rows: dict[Key, dict[str, Any]] = {}
        for concept in self.concepts:
            for prompt in prompts:
                task = prompt + (
                    f" Include {concept.label} in your answer." if cell["topical"] else ""
                )
                log.info("Generation %s %s %s/%s", identifier, concept.id, len(rows) + 1, 180)
                text, states = answer(
                    self.capture,
                    library,
                    concept.id,
                    task,
                    self.seed,
                    cell["alpha"],
                    cell["immune"],
                )
                hidden = np.stack([s.layer_hidden[readout] for s in states])
                z = (
                    unit(self.windows(hidden)) @ library.D.T - library.readout_mean
                ) / library.readout_std
                idx = self.ids.index(concept.id)
                projections = np.stack([s.defender_hidden for s in states]) @ library.V.T
                exempt = {self.ids.index(c) for c in library.mentioned_in(task)}
                alarm = detect(projections, z, library.alarm_thresholds, exempt=exempt)
                rank = np.argsort(-z[-1], kind="stable")
                keyword = bool(concept_pattern(concept).search(text))
                matches = [
                    (m.start(), self.ids.index(c.id))
                    for c in self.concepts
                    if (m := concept_pattern(c).search(text))
                ]
                keyword_rank = [i for _, i in sorted(matches)]
                embed_threshold = np.percentile(
                    [unit(n[readout].mean(axis=0)) @ library.D.T for n in self.embedding],
                    99,
                    axis=0,
                )
                full = np.concatenate(
                    [
                        np.stack([s.layer_hidden[i] for s in states]).mean(axis=0)
                        for i in [16, 20, 22]
                    ]
                )
                values = {
                    "keyword_hit": float(keyword),
                    "stem_hit": float(concept.id in library.mentioned_in(text)),
                    "embed_hit": float(
                        (unit(hidden.mean(axis=0)) @ library.D.T)[idx] > embed_threshold[idx]
                    ),
                    "task_kept": float(task_kept(task, text)),
                    "both": float(keyword and task_kept(task, text)),
                    "cosine_top1": float(rank[0] == idx),
                    "cosine_top3": float(idx in rank[:3]),
                    "keyword_top1": float(bool(keyword_rank) and keyword_rank[0] == idx),
                    "any_alarm": alarm["any_alarm"],
                    "token_alarm": alarm["token_alarm"],
                    "attribution": float(idx in alarm["flagged"]),
                }
                if self.primary_classifier is not None:
                    token_features = np.concatenate(
                        [
                            self.windows(np.stack([s.layer_hidden[i] for s in states]))
                            for i in [16, 20, 22]
                        ],
                        axis=1,
                    )
                    logits = self.primary_classifier.scores(token_features)
                    probability = np.exp(logits - logits.max(axis=1, keepdims=True))
                    probability /= probability.sum(axis=1, keepdims=True)
                    confidence = np.full_like(probability, -np.inf)
                    winner = probability.argmax(axis=1)
                    confidence[np.arange(len(winner)), winner] = (
                        probability.max(axis=1) - self.confidence_threshold
                    ) / self.confidence_std
                    classifier_alarm = detect(
                        projections,
                        confidence,
                        library.alarm_thresholds,
                        exempt=exempt,
                        z_threshold=0,
                    )
                    values["classifier_alarm"] = classifier_alarm["any_alarm"]
                    scores = self.primary_classifier.scores(full)
                    v4rank = np.argsort(-scores, kind="stable")
                    values.update(v4_top1=float(v4rank[0] == idx), v4_top3=float(idx in v4rank[:3]))
                rows[(concept.id, prompt, self.seed)] = {
                    "values": values,
                    "z": z,
                    "projections": projections,
                    "features": full,
                    "text_hash": text_hash(text),
                    "exempt": exempt,
                    "tokens": len(states),
                    "library_hash": library.hash,
                }
        self.trials[identifier] = rows
        return rows

    def v4(self, variants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        from nous.research.statistics import paired, summary

        self.backend.injection_layer, self.backend.readout_layer = 16, 20
        library = self.library()
        assert library.readout_mean is not None and library.readout_std is not None
        train, validation, test = generate_training(self.backend, library, log.info)
        check_partitions(train, validation, test)
        self.corpus_hashes.update(
            {
                name: [text_hash(e.text) for e in part]
                for name, part in (("train", train), ("validation", validation), ("test", test))
            }
        )
        rows, primary = [], {}
        for variant in variants:
            classifier = fit_variant(
                train, validation, test, self.ids, self.backend.hidden_size, variant
            )
            values, old, top3 = {}, {}, {}
            for e in test:
                key = (e.concept, e.family, e.seed)
                x = features(e.features, self.backend.hidden_size, variant["layers"])
                rank = np.argsort(-classifier.scores(x), kind="stable")
                values[key] = float(self.ids[rank[0]] == e.concept)
                top3[key] = float(e.concept in [self.ids[i] for i in rank[:3]])
                hidden = features(e.features, self.backend.hidden_size, [20])
                z = (unit(hidden) @ library.D.T - library.readout_mean) / library.readout_std
                old[key] = float(self.ids[int(np.argmax(z))] == e.concept)
            stats = {
                "top1": summary(values, seed=self.seed),
                "top3": summary(top3, seed=self.seed),
                "cosine_top1": summary(old, seed=self.seed),
                "paired_vs_cosine": paired(values, old, seed=self.seed),
            }
            row = variant | {
                "status": "run",
                "n": len(test),
                "clusters": len(self.ids),
                "planned_n": 360,
                "metrics": stats,
                "regularization": classifier.regularization,
                "validation_n": len(validation),
                "validation_accuracy": classifier.validation_accuracy,
                "training_n": variant["train_size"] * len(self.ids),
            }
            rows.append(row)
            if variant == {
                "layers": [16, 20, 22],
                "whitening": "standardize",
                "classifier": "lda",
                "train_size": 66,
            }:
                self.primary_classifier, primary = classifier, row
                np.savez(
                    self.output / "selected-readout.npz",
                    center=classifier.center,
                    transform=classifier.transform,
                    weights=classifier.weights,
                    bias=classifier.bias,
                )
            log.info("Readout variant %s/%s", len(rows), len(variants))
        if self.primary_classifier is not None:
            calibration, hashes = [], []
            for i in range(60):
                text, layers = uninjected(self.capture, PROMPTS[10 + i % 30], 70000 + self.seed + i)
                hashes.append(text_hash(text))
                x = np.concatenate([self.windows(layers[layer]) for layer in [16, 20, 22]], axis=1)
                scores = self.primary_classifier.scores(x)
                p = np.exp(scores - scores.max(axis=1, keepdims=True))
                calibration.extend((p / p.sum(axis=1, keepdims=True)).max(axis=1))
            if set(hashes) & {h for group in self.corpus_hashes.values() for h in group}:
                self.primary_classifier = None
                raise ValueError("Classifier-alarm calibration overlaps another corpus")
            self.corpus_hashes["classifier_alarm_validation"] = hashes
            self.confidence_threshold = float(np.percentile(calibration, 99.5))
            self.confidence_std = max(float(np.std(calibration)), 1e-6)
            library.readout_v4 = {
                "center": self.primary_classifier.center,
                "scale": 1 / self.primary_classifier.transform,
                "weights": self.primary_classifier.weights,
                "intercept": self.primary_classifier.bias,
                "shrinkage": np.array([self.primary_classifier.regularization]),
            }
            library.provenance["readout_v4"] = {
                "selection": "predefined primary; regularization selected on validation only",
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
            library.save(self.output / "fitted-library.npz")
        # The winner uses validation only; held-out ranks never select an architecture.
        selected = max(range(len(rows)), key=lambda i: (rows[i]["validation_accuracy"], -i))
        for i, row in enumerate(rows):
            row["selected_by_validation"] = i == selected
        return rows, primary

    def provenance(self) -> dict[str, Any]:
        libraries = {str(key): library.hash for key, library in sorted(self.libraries.items())}
        return {
            "library_hashes": libraries,
            "corpus_text_hashes": self.corpus_hashes,
            "vectors": {
                str(key): {
                    c: hashlib.sha256(np.ascontiguousarray(library.V[i]).tobytes()).hexdigest()
                    for i, c in enumerate(self.ids)
                }
                for key, library in sorted(self.libraries.items())
            },
            "corpus_hash": hashlib.sha256(
                json.dumps(self.corpus_hashes, sort_keys=True).encode()
            ).hexdigest(),
        }
