"""Build candidates privately; only a complete quality report can authorize publication."""

import copy
import json
import os
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from nous.concepts.builder import calibrate_alarm, mean_hidden, neutral_set, trace_answer
from nous.concepts.library import Concept, ConceptLibrary, config_hash, match_concept
from nous.concepts.policy import validate_name
from nous.concepts.probe import Example, text_hash
from nous.engine.generate import PROMPTS
from nous.engine.immune import unit
from nous.evaluation import embedding_thresholds, fit_readout, generate_training, run_trial
from nous.model.backend import ModelBackend


@dataclass(frozen=True)
class BuildResult:
    report: dict[str, Any]
    library: ConceptLibrary | None = None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def unavailable(name: str, reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "rejected",
        "source": "unavailable",
        "origin": {
            "source": "from-model",
            "requested_count": 24,
            "texts": [],
            "seed": 0,
            "model": "Qwen/Qwen2.5-0.5B-Instruct",
            "status": "unrun",
            "texts_hash": None,
        },
        "reasons": [reason],
        "checks": {
            key: {"status": "unrun", "n": 0, "value": None, "threshold": threshold}
            for key, threshold in (
                ("heldout_top1", 0.8),
                ("max_cosine", 0.6),
                ("injection_gain", 0.10),
                ("task_kept", 0.6),
            )
        },
    }


def load_examples(path: Path) -> list[str]:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Example file is too large")
    if path.suffix in {".yaml", ".yml", ".json"}:
        rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        rows = path.read_text(encoding="utf-8").splitlines()
    if not isinstance(rows, list) or any(not isinstance(s, str) or not s.strip() for s in rows):
        raise ValueError("Examples must be a list of nonempty sentences")
    if not 4 <= len(rows) <= 128:
        raise ValueError("Supply between four and 128 sentences")
    return rows


class TopicBuilder:
    def __init__(self, backend: ModelBackend, library: ConceptLibrary, *, seed: int = 0) -> None:
        self.backend, self.base, self.seed = backend, library, seed
        self.model = str(library.config.get("model", "unknown"))
        self.attempts: list[dict[str, Any]] = []
        template = Path("data/builder_prompts.yaml")
        content = (
            template.read_text(encoding="utf-8")
            if template.is_file()
            else files("nous.concepts").joinpath("builder_prompts.yaml").read_text()
        )
        self.prompts = yaml.safe_load(content)
        if not isinstance(self.prompts, dict) or not all(
            isinstance(self.prompts.get(key), str) for key in ["concept", "neutral"]
        ):
            raise ValueError("Builder templates must provide concept and neutral prompts")
        try:
            self.prompts["concept"].format(name="topic")
            self.prompts["neutral"].format(length=12)
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError("Invalid builder template placeholders") from exc

    def capture(self, texts: list[str]) -> dict[str, list[float]]:
        return {
            str(layer): mean_hidden(self.backend, texts, layer).tolist()
            for layer in {self.backend.injection_layer, self.backend.readout_layer}
        }

    def generate(
        self, name: str, count: int
    ) -> tuple[list[str], dict[str, list[float]], dict[str, Any]]:
        rng = np.random.default_rng(self.seed)
        rows: list[str] = []
        seen: set[str] = set()
        layers: list[dict[int, Any]] = []
        neutral: list[str] = []
        attempt: dict[str, Any] = {
            "name": name,
            "source": "from-model",
            "seed": self.seed,
            "model": self.model,
            "requested_count": count,
            "texts": rows,
            "neutral_texts": neutral,
            "attempted_texts": [],
            "status": "incomplete",
            "prompt_hash": config_hash(self.prompts),
        }
        self.attempts.append(attempt)
        for _ in range(count * 5):
            text, hidden, _ = trace_answer(
                self.backend, self.prompts["concept"].format(name=name), rng
            )
            if text_hash(text) in seen:
                continue
            seen.add(text_hash(text))
            attempt["attempted_texts"].append(text)
            length = len(text.split())
            if length < 2:
                continue
            # Matching is explicit and audited; no repeated filler is used to make lengths fit.
            for _attempt in range(5):
                plain, _, _ = trace_answer(
                    self.backend,
                    self.prompts["neutral"].format(length=length),
                    rng,
                    max_tokens=max(32, length * 3),
                )
                words = plain.split()
                if len(words) >= length:
                    neutral.append(" ".join(words[:length]))
                    break
            else:
                raise ValueError("Could not generate a length-matched neutral sentence")
            rows.append(text)
            layers.append(hidden)
            if len(rows) == count:
                break
        if len(rows) != count:
            raise ValueError("Not enough distinct generated sentences")
        means = {
            str(layer): np.concatenate([h[layer] for h in layers]).mean(axis=0).tolist()
            for layer in {self.backend.injection_layer, self.backend.readout_layer}
        }
        origin = {
            "texts": rows,
            "neutral_texts": neutral,
            "length_unit": "words",
            "seed": self.seed,
            "model": self.model,
            "source": "from-model",
            "prompt_hash": config_hash(self.prompts),
            "texts_hash": config_hash({"texts": rows}),
            "raw_means": means,
        }
        # Held-out fitting uses actual generated states, not a second encoding with a new context.
        origin["sample_means"] = {
            str(layer): [h[layer].mean(axis=0).tolist() for h in layers]
            for layer in {self.backend.injection_layer, self.backend.readout_layer}
        }
        origin["sample_counts"] = [len(h[self.backend.readout_layer]) for h in layers]
        attempt.update(origin, status="complete")
        return rows, means, origin

    def sources(self) -> dict[str, Any]:
        sources = copy.deepcopy(self.base.provenance.get("concept_origins", {}))
        for concept in self.base.concepts:
            if concept.id not in sources:
                _, _, sources[concept.id] = self.generate(concept.label, 24)
                sources[concept.id]["reason"] = "Earlier library did not retain source texts"
            elif "raw_means" not in sources[concept.id]:
                sources[concept.id]["raw_means"] = self.capture(sources[concept.id]["texts"])
                sources[concept.id]["encoding"] = "source text, absolute position zero excluded"
        return sources

    def library(
        self, name: str, sources: dict[str, Any], means: dict[str, list[float]]
    ) -> ConceptLibrary:
        concepts = [
            *self.base.concepts,
            Concept(
                name,
                name.replace("-", " ").title(),
                len(self.base.ids) % 7,
                (name.replace("-", " "),),
            ),
        ]
        directions = []
        for layer in [self.backend.injection_layer, self.backend.readout_layer]:
            rows = np.array(
                [sources[c.id]["raw_means"][str(layer)] for c in self.base.concepts]
                + [means[str(layer)]]
            )
            directions.append(unit(rows - (rows.sum(axis=0) - rows) / (len(rows) - 1)))
        config = copy.deepcopy(self.base.config)
        config.update(
            variant="others",
            injection_layer=self.backend.injection_layer,
            readout_layer=self.backend.readout_layer,
            seed=self.seed,
            excluded_positions=[0],
            probe_layers=sorted(
                {
                    self.backend.injection_layer,
                    self.backend.readout_layer,
                    min(22, self.backend.num_layers - 1),
                }
            ),
        )
        return ConceptLibrary(
            concepts,
            directions[0],
            directions[1],
            np.zeros(self.backend.hidden_size),
            np.zeros(len(concepts)),
            config,
            provenance={"concept_origins": sources},
        )

    def recalibrate(self, library: ConceptLibrary) -> None:
        neutral = neutral_set(self.backend, 60, self.seed + 40000)
        positions = np.concatenate([row[1][self.backend.readout_layer] for row in neutral])
        cosines = unit(positions) @ library.D.T
        library.readout_mean = cosines.mean(axis=0)
        library.readout_std = np.maximum(cosines.std(axis=0), 1e-6)
        library.thresholds = np.percentile(
            np.concatenate([row[2] for row in neutral]) @ library.V.T, 97, axis=0
        )
        library.config["readout_calibration_seed"] = self.seed + 40000
        library.provenance["calibration_text_hashes"] = [text_hash(row[0]) for row in neutral]
        calibrate_alarm(self.backend, library, count=60, seed=self.seed + 50000)
        calibration: list[Example] = []
        parts = generate_training(self.backend, library, calibration=calibration)
        library.provenance["readout_fit"] = fit_readout(
            library, *parts, seed=self.seed, calibration=calibration
        )
        if not library.readout_v4 or library.readout_v4["weights"].shape[0] != len(library.ids):
            raise ValueError("The expanded Mind-Reader was not fitted")
        library.layout()

    def build(
        self, name: str, *, count: int = 24, examples: list[str] | None = None
    ) -> BuildResult:
        name = validate_name(name)
        self.attempts = []
        report = unavailable(name, "Build incomplete")
        report["attempts"] = self.attempts
        report.update(source=self.model, base_hash=self.base.hash, seed=self.seed)
        report["origin"].update(
            source="examples" if examples is not None else "from-model",
            texts=examples if examples is not None else [],
            seed=self.seed,
            model=self.model,
            requested_count=len(examples) if examples is not None else count,
            texts_hash=config_hash({"texts": examples}) if examples is not None else None,
        )
        if match_concept(name, self.base.concepts) is not None:
            report["reasons"] = ["This topic is already in the library"]
            return BuildResult(report)
        try:
            if not 4 <= count <= 128:
                raise ValueError("Use between four and 128 generated sentences")
            if examples is None:
                texts, means, origin = self.generate(name, count)
            else:
                if not 4 <= len(examples) <= 128 or any(not text.strip() for text in examples):
                    raise ValueError("Supply between four and 128 nonempty sentences")
                texts, means = examples, self.capture(examples)
                origin = {
                    "texts": texts,
                    "source": "examples",
                    "seed": self.seed,
                    "model": self.model,
                    "texts_hash": config_hash({"texts": texts}),
                    "raw_means": means,
                }
            report["origin"] = origin
            if len({text_hash(s) for s in texts}) != len(texts):
                raise ValueError("Repeated examples cannot form an independent held-out check")
            sources = self.sources()
            report["reference_sources"] = sources
            order = np.random.default_rng(self.seed).permutation(len(texts))
            half = len(order) // 2
            if examples is None:
                train_means = {
                    layer: np.average(
                        np.asarray(rows)[order[:half]],
                        axis=0,
                        weights=np.asarray(origin["sample_counts"])[order[:half]],
                    ).tolist()
                    for layer, rows in origin["sample_means"].items()
                }
                hidden = np.asarray(origin["sample_means"][str(self.backend.readout_layer)])[
                    order[half:]
                ]
            else:
                train_means = self.capture([texts[i] for i in order[:half]])
                hidden = self.backend.embed_texts(
                    [texts[i] for i in order[half:]], self.backend.readout_layer
                )
            provisional = self.library(name, sources, train_means)
            ranks = np.argmax(unit(hidden) @ provisional.D.T, axis=1)
            top1 = float(np.mean(ranks == len(self.base.ids)))
            candidate = self.library(name, sources, means)
            cosine = max(
                float(np.max(candidate.V[-1] @ unit(self.base.V).T)),
                float(np.max(candidate.D[-1] @ unit(self.base.D).T)),
            )
            report["checks"]["heldout_top1"].update(
                status="run", n=len(hidden), value=top1, passed=top1 >= 0.8
            )
            report["checks"]["max_cosine"].update(
                status="run", n=len(self.base.ids), value=cosine, passed=cosine <= 0.6
            )
            report["split"] = {"train": order[:half].tolist(), "heldout": order[half:].tolist()}
            if top1 < 0.8 or cosine > 0.6:
                report["reasons"] = [
                    key
                    for key in ["heldout_top1", "max_cosine"]
                    if not report["checks"][key]["passed"]
                ]
                return BuildResult(report)
            tau, calibration = embedding_thresholds(self.backend, candidate, seed=self.seed + 60000)
            prompts = [p for p in PROMPTS if not candidate.mentioned_in(p)][:6]
            if len(prompts) != 6:
                raise ValueError("Six non-topical evaluation prompts are required")
            trials = {
                alpha: [
                    run_trial(
                        self.backend,
                        candidate,
                        concept=name,
                        prompt=p,
                        seed=self.seed,
                        alpha=alpha,
                        immune=False,
                        embed_tau=tau,
                    )
                    for p in prompts
                ]
                for alpha in (0.0, 0.45)
            }
            rates = {
                str(alpha): {
                    metric: float(np.mean([t.values[metric][0] for t in rows]))
                    for metric in ["keyword_hit", "embed_hit", "task_kept"]
                }
                for alpha, rows in trials.items()
            }
            gain = max(
                rates["0.45"][key] - rates["0.0"][key] for key in ["keyword_hit", "embed_hit"]
            )
            kept = rates["0.45"]["task_kept"]
            report["evaluation"] = {
                "n": 6,
                "prompts": prompts,
                "rates": rates,
                "embedding_calibration_hash": config_hash({"texts": calibration}),
            }
            report["checks"]["injection_gain"].update(
                status="run", n=6, value=gain, passed=gain >= 0.10
            )
            report["checks"]["task_kept"].update(status="run", n=6, value=kept, passed=kept >= 0.6)
            report["reasons"] = [
                k for k, check in report["checks"].items() if not check.get("passed")
            ]
            if report["reasons"]:
                return BuildResult(report)
            sources[name] = origin
            candidate.provenance["concept_origins"] = sources
            self.recalibrate(candidate)
            report.update(
                status="accepted",
                library_hash=candidate.hash,
                vector_hash=candidate.vector_hashes[name],
                layout_hash=config_hash(candidate.layout()),
            )
            report["report_hash"] = config_hash(report)
            return BuildResult(report, candidate)
        except (ValueError, RuntimeError, OSError, ImportError) as exc:
            report["reasons"] = [str(exc)]
            return BuildResult(report)


def approved(result: BuildResult) -> bool:
    report, library = result.report, result.library
    if library is None or report.get("status") != "accepted":
        return False
    if not library.readout_v4 or library.alarm_thresholds is None:
        return False
    expected = {
        "heldout_top1": (0.8, True),
        "max_cosine": (0.6, False),
        "injection_gain": (0.10, True),
        "task_kept": (0.6, True),
    }
    for key, (threshold, minimum) in expected.items():
        check = report.get("checks", {}).get(key, {})
        value = check.get("value")
        if (
            check.get("status") != "run"
            or check.get("n", 0) <= 0
            or (key in {"injection_gain", "task_kept"} and check.get("n") != 6)
            or check.get("threshold") != threshold
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or (value < threshold if minimum else value > threshold)
        ):
            return False
    return report.get("library_hash") == library.hash


def save_result(result: BuildResult, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if approved(result):
        assert result.library is not None
        result.library.save(directory / "library.npz")
    else:
        if result.report.get("status") == "accepted":
            result.report.update(
                status="rejected", reasons=["The quality report did not authorize publication"]
            )
        (directory / "library.npz").unlink(missing_ok=True)
    for attempt in result.report.get("attempts", []):
        attempt["texts_hash"] = config_hash({"texts": attempt["texts"]})
    payload = {k: v for k, v in result.report.items() if k != "report_hash"}
    result.report["report_hash"] = config_hash(payload)
    write_json(directory / "quality.json", result.report)
