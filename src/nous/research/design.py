"""Explicit one-factor cells; dimensions never silently narrow when artifacts are absent."""

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import yaml

REGISTERED_DESIGN = "17556d9e43b3d11f9c9fc7d658069bec8bc6aa4f9254ea76f6745adf6450b506"
REGISTRATION = "b1a090fc7d7325207f792b9cfe88dc3a01014d9b"
ROOT = next(
    (
        candidate
        for candidate in (Path.cwd(), *Path.cwd().parents, *Path(__file__).resolve().parents)
        if (candidate / "docs/hypotheses.md").is_file()
    ),
    Path.cwd(),
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise TypeError("Research configuration must be a mapping")
    required = yaml.safe_load((ROOT / "configs/ablations.yaml").read_text())
    if data.keys() != required.keys():
        raise ValueError("Configuration must state every registered dimension")
    if data["model"] != "Qwen/Qwen2.5-0.5B-Instruct":
        raise ValueError("Only the registered local model is supported")
    if (
        data["concepts"] != 30
        or data["prompts"] != 6
        or data["bootstrap"] != 2000
        or data["neutral_generations"] < 60
        or data["max_tokens"] != 32
    ):
        raise ValueError("Changing the registered sampling design requires a new registration")
    design = {k: v for k, v in data.items() if k != "model_path"}
    if hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest() != REGISTERED_DESIGN:
        raise ValueError("Unregistered design change")
    if data["model_path"] is not None and not isinstance(data["model_path"], str):
        raise TypeError("Model path must be a string or null")
    for name in required.keys() - {"model_path"}:
        if data[name] != required[name]:
            raise ValueError(f"Unregistered design change: {name}")
    return data


def cell_id(cell: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cell, sort_keys=True).encode()).hexdigest()[:16]


def plan(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    base = {
        "layer": 16,
        "readout": 20,
        "alpha": 0.45,
        "vector": "others",
        "immune": False,
        "topical": False,
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for name, key, values in (
        ("dose", "alpha", config["alphas"]),
        ("injection_layer", "layer", config["injection_layers"]),
        ("vector", "vector", config["vectors"]),
        ("readout_layer", "readout", config["readout_layers"]),
    ):
        rows = []
        for value in values:
            for alpha in [value] if name == "dose" else [0, 0.45]:
                rows.append(base | {key: value, "alpha": alpha})
        result[name] = rows
    result["immune"] = [
        base | {"alpha": a, "immune": i, "topical": t}
        for a, i, t in itertools.product([0, 0.45], [False, True], [False, True])
    ]
    result["v4"] = [
        {"layers": layers, "whitening": w, "classifier": c, "train_size": n}
        for layers, w, c, n in itertools.product(
            config["v4_layers"],
            config["v4_whitening"],
            config["v4_classifiers"],
            config["v4_training_sizes"],
        )
    ]
    result["alarm"] = [
        {"percentile": p, "z": z, "run": r, "exempt": e, "alpha": a, "immune": i, "topical": t}
        for p, z, r, e, a, i, t in itertools.product(
            config["alarm_percentiles"],
            config["alarm_z"],
            config["alarm_runs"],
            [False, True],
            [0, 0.45],
            [False, True],
            [False, True],
        )
    ]
    return result
