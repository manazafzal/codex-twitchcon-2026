import json
from pathlib import Path

import numpy as np

from nous.concepts.library import ConceptLibrary, config_hash
from nous.concepts.probe import Example


def basis_hash(library: ConceptLibrary) -> str:
    return config_hash(
        {
            "vectors": library.vector_hashes,
            "ids": library.ids,
            "thresholds": library.thresholds.tolist(),
            "model": library.config.get("model"),
            "probe_layers": library.config.get("probe_layers"),
        }
    )


def save_examples(
    path: Path, parts: tuple[list[Example], list[Example], list[Example]], library: ConceptLibrary
) -> None:
    rows = [e for part in parts for e in part]
    metadata = [
        {"text": e.text, "concept": e.concept, "family": e.family, "seed": e.seed, "mode": e.mode}
        for e in rows
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        features=np.stack([e.features for e in rows]),
        metadata=json.dumps(metadata),
        sizes=np.array([len(part) for part in parts]),
        library_hash=library.hash,
        basis_hash=basis_hash(library),
    )


def load_examples(
    path: Path, library: ConceptLibrary
) -> tuple[list[Example], list[Example], list[Example]]:
    with np.load(path, allow_pickle=False) as data:
        if str(data["library_hash"]) != library.hash and (
            "basis_hash" not in data or str(data["basis_hash"]) != basis_hash(library)
        ):
            raise ValueError("Training data came from a different library")
        metadata = json.loads(str(data["metadata"]))
        rows = [
            Example(**row, features=features)
            for row, features in zip(metadata, data["features"], strict=True)
        ]
        a, b, c = map(int, data["sizes"])
        if min(a, b, c) < 1 or a + b + c != len(rows):
            raise ValueError("Invalid partition sizes")
        return rows[:a], rows[a : a + b], rows[a + b :]
