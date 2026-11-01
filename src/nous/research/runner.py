"""Run every registered cell offline, retaining explicit reasons for unavailable evidence."""

import itertools
import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from nous.concepts.builder import git_revision
from nous.research.design import REGISTRATION, ROOT, cell_id, digest, load_config, plan
from nous.research.statistics import paired, reduction, summary

log = logging.getLogger(__name__)


def observations(rows: dict[Any, Any], metric: str) -> dict[Any, float]:
    return {key: row["values"][metric] for key, row in rows.items() if metric in row["values"]}


def summarize(rows: dict[Any, Any], seed: int) -> dict[str, Any]:
    names = sorted(set.intersection(*(set(row["values"]) for row in rows.values())))
    return {
        name: summary(observations(rows, name), seed=seed, binary=name != "token_alarm")
        for name in names
    }


def blank(cell: dict[str, Any], reason: str, n: int = 180) -> dict[str, Any]:
    return cell | {
        "status": "unrun",
        "n": 0,
        "clusters": 0,
        "planned_n": n,
        "reason": reason,
        "metrics": {},
    }


def verify_registration() -> None:
    committed = subprocess.check_output(
        ["git", "show", f"{REGISTRATION}:docs/hypotheses.md"], cwd=ROOT
    )
    if committed != (ROOT / "docs/hypotheses.md").read_bytes():
        raise ValueError("Registered hypotheses changed; register a new design first")
    files = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", REGISTRATION],
        cwd=ROOT,
        text=True,
    ).splitlines()
    if files != ["docs/hypotheses.md"]:
        raise ValueError("Registration must be a file-only commit")


def comparisons(experiment: Any, tables: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    base = {
        "layer": 16,
        "readout": 20,
        "alpha": 0.45,
        "vector": "others",
        "immune": False,
        "topical": False,
    }
    rows = []

    def values(cell: dict[str, Any], metric: str) -> dict[Any, float]:
        return observations(experiment.trials.get(cell_id(cell), {}), metric)

    def compare(name: str, left: dict[str, Any], right: dict[str, Any], metric: str) -> None:
        a, b = values(left, metric), values(right, metric)
        row = {"comparison": name, "metric": metric, "planned_n": 180}
        if a and a.keys() == b.keys():
            row.update(status="run", **paired(a, b, seed=seed))
        else:
            row.update(
                status="unrun",
                n=0,
                clusters=0,
                mean=None,
                cluster_ci95=None,
                reason="Matched complete generations unavailable",
            )
        rows.append(row)

    compare("H1 dose minus control", base, base | {"alpha": 0}, "keyword_hit")
    for a, b in zip(experiment.config["alphas"][1:], experiment.config["alphas"][:-1]):
        compare(f"H2 task {a} minus {b}", base | {"alpha": a}, base | {"alpha": b}, "task_kept")
    for method in ["neutral", "raw"]:
        for metric in ["keyword_hit", "cosine_top1"]:
            compare(f"H3 others minus {method}", base, base | {"vector": method}, metric)
    a, b = values(base, "cosine_top1"), values(base, "keyword_hit")
    rows.append(
        dict(
            comparison="H4 cosine minus target keyword",
            metric="top1",
            planned_n=180,
            status="run",
            **paired(a, b, seed=seed),
        )
        if a and a.keys() == b.keys()
        else {
            "comparison": "H4 cosine minus target keyword",
            "status": "unrun",
            "n": 0,
            "clusters": 0,
            "planned_n": 180,
            "reason": "Primary generations unavailable",
        }
    )
    compare("H5 immune on minus off", base | {"immune": True}, base, "keyword_hit")
    off, on = values(base, "keyword_hit"), values(base | {"immune": True}, "keyword_hit")
    if off and off.keys() == on.keys():
        rows.append(
            dict(
                comparison="H5 relative reduction",
                status="run",
                planned_n=180,
                **reduction(off, on, seed=seed),
            )
        )
    else:
        rows.append(
            {
                "comparison": "H5 relative reduction",
                "status": "unrun",
                "n": 0,
                "clusters": 0,
                "planned_n": 180,
                "reason": "Matched immune generations unavailable",
            }
        )
    neutral = base | {"alpha": 0}
    a, b = values(neutral, "classifier_alarm"), values(neutral, "any_alarm")
    rows.append(
        dict(
            comparison="H7 classifier minus cosine false alarms",
            metric="any_alarm",
            planned_n=180,
            status="run",
            **paired(a, b, seed=seed),
        )
        if a and a.keys() == b.keys()
        else {
            "comparison": "H7 classifier minus cosine false alarms",
            "status": "unrun",
            "n": 0,
            "clusters": 0,
            "planned_n": 180,
            "reason": "Independent classifier calibration unavailable",
        }
    )
    groups = [
        [values(base | {"layer": layer}, "keyword_hit") for layer in layers]
        for layers in [[9, 12, 13, 16], [18, 20]]
    ]
    flattened = [v for group in groups for v in group]
    if all(flattened) and all(v.keys() == flattened[0].keys() for v in flattened):
        means = [
            {k: float(np.mean([v[k] for v in group])) for k in flattened[0]} for group in groups
        ]
        rows.append(
            dict(
                comparison="H8 middle minus late",
                status="run",
                planned_n=180,
                **paired(*means, seed=seed),
            )
        )
    else:
        rows.append(
            {
                "comparison": "H8 middle minus late",
                "status": "unrun",
                "n": 0,
                "clusters": 0,
                "planned_n": 180,
                "reason": "Complete matched layer grid unavailable",
            }
        )
    return rows


def control_comparisons(experiment: Any, cells: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    result = []
    for name in ["dose", "injection_layer", "vector", "readout_layer", "immune"]:
        for cell in cells[name]:
            if not cell["alpha"]:
                continue
            a = experiment.trials.get(cell_id(cell), {})
            b = experiment.trials.get(cell_id(cell | {"alpha": 0}), {})
            if not a or a.keys() != b.keys():
                result.append(
                    blank(cell | {"grid": name}, "Complete matched alpha-zero control unavailable")
                )
                continue
            names = sorted(
                set.intersection(*(set(r["values"]) for r in [*a.values(), *b.values()]))
            )
            metrics = {m: paired(observations(a, m), observations(b, m), seed=seed) for m in names}
            result.append(
                cell
                | {
                    "grid": name,
                    "status": "run",
                    "n": len(a),
                    "clusters": 30,
                    "planned_n": 180,
                    "metrics": metrics,
                }
            )
    return result


def alarm_rows(experiment: Any, cells: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    from nous.research.alarms import detect

    library = experiment.library()
    neutral_projections = np.concatenate([n[17] for n in experiment.fresh]) @ library.V.T
    rows = []
    for cell in cells:
        generation = {
            "layer": 16,
            "readout": 20,
            "vector": "others",
            "alpha": cell["alpha"],
            "immune": cell["immune"],
            "topical": cell["topical"],
        }
        traces = experiment.trials.get(cell_id(generation), {})
        if not traces:
            rows.append(blank(cell, "Matched immune trace unavailable"))
            continue
        thresholds = np.percentile(neutral_projections, cell["percentile"], axis=0)
        values = {}
        deltas = {}
        for key, trace in traces.items():
            result = detect(
                trace["projections"],
                trace["z"],
                thresholds,
                run=cell["run"],
                z_threshold=cell["z"],
                exempt=trace["exempt"] if cell["exempt"] else set(),
            )
            without = detect(
                trace["projections"],
                trace["z"],
                thresholds,
                run=cell["run"],
                z_threshold=cell["z"],
                exempt=set(),
            )
            idx = experiment.ids.index(key[0])
            deltas[key] = {
                "any_alarm": result["any_alarm"] - without["any_alarm"],
                "attribution": float(idx in result["flagged"]) - float(idx in without["flagged"]),
                "token_alarm": result["token_alarm"] - without["token_alarm"],
            }
            values[key] = {
                "values": {
                    "any_alarm": result["any_alarm"],
                    "token_alarm": result["token_alarm"],
                    "attribution": float(idx in result["flagged"]),
                }
            }
        rows.append(
            cell
            | {
                "status": "run",
                "n": len(traces),
                "clusters": 30,
                "planned_n": 180,
                "metrics": summarize(values, seed),
                "paired_exemption_vs_none": {
                    m: summary({k: v[m] for k, v in deltas.items()}, seed=seed, binary=False)
                    for m in ["any_alarm", "attribution", "token_alarm"]
                },
            }
        )
    return rows


def conclusions(tables: dict[str, Any]) -> list[dict[str, Any]]:
    """Point rules and interval rules are separate; crossing zero is inconclusive."""
    primary = {
        "layer": 16,
        "readout": 20,
        "alpha": 0.45,
        "vector": "others",
        "immune": False,
        "topical": False,
    }

    def find(table: str, conditions: dict[str, Any]) -> dict[str, Any]:
        return next(
            (r for r in tables[table] if all(r.get(k) == v for k, v in conditions.items())), {}
        )

    def metric(table: str, cond: dict[str, Any], name: str) -> dict[str, Any]:
        row = find(table, cond)
        return row.get("metrics", {}).get(name, {}) if row.get("status") == "run" else {}

    def cmp(name: str) -> dict[str, Any]:
        return find("paired", {"comparison": name})

    decisions = []

    def record(number: int, checks: list[Any], n: int, reason: str) -> None:
        status = "unrun" if not checks or any(x is None for x in checks) else "run"
        outcome = (
            "unrun"
            if status == "unrun"
            else "not supported"
            if any(x is False for x in checks)
            else "inconclusive"
            if "inconclusive" in checks
            else "supported"
        )
        decisions.append(
            {
                "hypothesis": f"H{number}",
                "status": status,
                "n": n if status == "run" else 0,
                "clusters": 30 if status == "run" else 0,
                "decision": outcome,
                "reason": reason,
            }
        )

    def lower(row: dict[str, Any], threshold: float, *, inclusive: bool = False) -> Any:
        ci = row.get("cluster_ci95")
        if ci is None:
            return None
        supported = ci[0] >= threshold if inclusive else ci[0] > threshold
        rejected = ci[1] < threshold if inclusive else ci[1] <= threshold
        return supported if supported or rejected else "inconclusive"

    record(1, [lower(cmp("H1 dose minus control"), 0)], 180, "Paired keyword difference")
    dose = [r for r in tables["dose"] if r["status"] == "run"]
    if len(dose) == 9:
        task = [r["metrics"]["task_kept"]["mean"] for r in dose]
        sweet = any(
            r["metrics"]["keyword_hit"]["mean"] >= 0.2 and r["metrics"]["task_kept"]["mean"] >= 0.7
            for r in dose
        )
        monotonic = all(a >= b for a, b in itertools.pairwise(task))
        record(
            2,
            [monotonic, sweet],
            1620,
            "Separate monotonic point-estimate and sweet-spot rules",
        )
        decisions[-1].update(monotonic=monotonic, sweet_spot=sweet)
    else:
        record(2, [], 0, "Complete dose grid unavailable")
    record(
        3,
        [
            lower(
                find("paired", {"comparison": f"H3 others minus {method}", "metric": m}),
                0,
                inclusive=True,
            )
            for method in ["neutral", "raw"]
            for m in ["keyword_hit", "cosine_top1"]
        ],
        180,
        "Nonnegative paired bounds on both outcomes against both baselines",
    )
    read = metric("dose", primary, "cosine_top1")
    record(
        4,
        [read["mean"] >= 0.9 if read else None, lower(cmp("H4 cosine minus target keyword"), 0)],
        180,
        "Blind all-concept cosine readout",
    )
    red = cmp("H5 relative reduction")
    immune_task = metric("immune", primary | {"immune": True}, "task_kept")
    false = metric("immune", primary | {"alpha": 0, "immune": True}, "any_alarm")
    record(
        5,
        [
            red["mean"] >= 0.8
            if red.get("mean") is not None
            else "inconclusive"
            if red.get("status") == "run"
            else None,
            immune_task["mean"] >= 0.95 if immune_task else None,
            false["mean"] <= 0.1 if false else None,
        ],
        180,
        "Relative reduction, task proxy and neutral false alarms; ratio undefined for zero control",
    )
    v4 = metric(
        "v4",
        {"layers": [16, 20, 22], "whitening": "standardize", "classifier": "lda", "train_size": 66},
        "top1",
    )
    delta = metric(
        "v4",
        {"layers": [16, 20, 22], "whitening": "standardize", "classifier": "lda", "train_size": 66},
        "paired_vs_cosine",
    )
    record(
        6, [lower(v4, 0.85), lower(delta, 0)], 360, "Disjoint held-out families, seeds and hashes"
    )
    off = metric("immune", primary, "v4_top1")
    on = metric("immune", primary | {"immune": True}, "v4_top1")
    record(
        7,
        [
            off["mean"] >= 0.97 if off else None,
            on["mean"] >= 0.95 if on else None,
            cmp("H7 classifier minus cosine false alarms")["mean"] > 0
            if cmp("H7 classifier minus cosine false alarms").get("mean") is not None
            else None,
        ],
        180,
        "Matched injected accuracy and independent neutral detector comparison",
    )
    record(
        8,
        [lower(cmp("H8 middle minus late"), 0)],
        180,
        "Paired mean middle-layer minus late-layer hit",
    )
    for row in decisions:
        if row["status"] == "unrun":
            row["decision"] = "unrun; required component unavailable"
    return decisions


def run_research(config_path: Path, seed: int, output: Path) -> dict[str, Any]:
    from nous.research.report import write_artifacts

    if seed < 0:
        raise ValueError("Research seed must be nonnegative")
    verify_registration()
    config = load_config(config_path)
    cells = plan(config)
    output.mkdir(parents=True, exist_ok=True)
    for generated in ["fitted-library.npz", "selected-readout.npz", "observations.json"]:
        (output / generated).unlink(missing_ok=True)
    reason = "Local trained model unavailable; no runtime download or substitute evidence"
    tables = {
        name: [blank(c, reason, 360 if name == "v4" else 180) for c in rows]
        for name, rows in cells.items()
    }
    experiment = None
    errors = []
    model_path = config["model_path"] or os.getenv("NOUS_MODEL_PATH")
    if model_path and (Path(model_path) / "config.json").is_file():
        from nous.model.hf_backend import HFBackend
        from nous.research.experiment import Experiment

        try:
            import torch

            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            torch.manual_seed(seed)
            backend = HFBackend(config["model"], device="cpu", local_path=str(model_path))
            experiment = Experiment(backend, config, seed, output)
            experiment.corpus()
        except (OSError, ValueError, ImportError, RuntimeError) as exc:
            errors.append(f"Corpus unavailable: {type(exc).__name__}: {exc}")
            experiment = None
        if experiment is not None:
            try:
                tables["v4"], _ = experiment.v4(cells["v4"])
                errors.extend(experiment.readout_failures)
            except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
                experiment.primary_classifier = None
                for generated in ["fitted-library.npz", "selected-readout.npz"]:
                    (output / generated).unlink(missing_ok=True)
                errors.append(f"Readout unavailable: {type(exc).__name__}: {exc}")
                tables["v4"] = [blank(c, errors[-1], 360) for c in cells["v4"]]
            for name in ["dose", "injection_layer", "vector", "readout_layer", "immune"]:
                for i, cell in enumerate(cells[name]):
                    try:
                        traces = experiment.generation(cell)
                        tables[name][i] = cell | {
                            "status": "run",
                            "n": len(traces),
                            "clusters": 30,
                            "planned_n": 180,
                            "metrics": summarize(traces, seed),
                        }
                    except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
                        error = f"{name}/{i}: {type(exc).__name__}: {exc}"
                        errors.append(error)
                        tables[name][i] = blank(cell, error)
            tables["alarm"] = alarm_rows(experiment, cells["alarm"], seed)
            tables["paired"] = comparisons(experiment, tables, seed)
    if experiment is None:
        from types import SimpleNamespace

        empty = SimpleNamespace(config=config, trials={})
        tables["paired"] = comparisons(empty, tables, seed)
        tables["paired_control"] = control_comparisons(empty, cells, seed)
        if errors:
            for rows in tables.values():
                for row in rows:
                    row["reason"] = errors[-1]
    else:
        tables["paired_control"] = control_comparisons(experiment, cells, seed)
    tables["hypotheses"] = conclusions(tables)
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str | None] = {}
    for package in ["numpy", "torch", "transformers", "matplotlib"]:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    model_files = (
        {
            str(p.relative_to(str(model_path))): digest(p)
            for p in sorted(Path(str(model_path)).iterdir())
            if p.is_file() and p.suffix in {".json", ".safetensors", ".bin", ".txt", ".model"}
        }
        if experiment
        else {}
    )
    manifest = {
        "package_versions": versions,
        "model_file_sha256": model_files,
        "schema": 1,
        "source": "realmodel",
        "model": config["model"],
        "seed": seed,
        "registration_commit": REGISTRATION,
        "hypotheses_sha256": digest(ROOT / "docs/hypotheses.md"),
        "config_sha256": digest(config_path),
        "config": config,
        "git_hash": git_revision(),
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "bootstrap_resamples": 2000,
        "errors": errors,
        "execution": "CPU deterministic algorithms, one thread; no network",
        "provenance": experiment.provenance() if experiment else {},
    }
    if experiment is not None:
        from nous.research.report import stable_json

        audit = [
            {
                "cell": identifier,
                "concept": key[0],
                "prompt": key[1],
                "seed": key[2],
                "values": trace["values"],
                "text_hash": trace["text_hash"],
                "tokens": trace["tokens"],
            }
            for identifier, traces in sorted(experiment.trials.items())
            for key, trace in sorted(traces.items())
        ]
        (output / "observations.json").write_text(stable_json(audit))
    manifest["completed_generation_answers"] = (
        sum(len(t) for t in experiment.trials.values()) if experiment else 0
    )
    manifest["availability"] = "local model executed" if experiment else "unavailable"
    write_artifacts(output, tables, manifest)
    log.info(
        "Research output: %s; run cells: %s; unrun cells: %s",
        output,
        sum(r["status"] == "run" for rows in tables.values() for r in rows),
        sum(r["status"] == "unrun" for rows in tables.values() for r in rows),
    )
    return {"tables": tables, "manifest": manifest}
