"""Offline detector comparisons leave the operational clamp unchanged."""

from typing import Any

import numpy as np

from nous.model.backend import Vector


def detect(
    projections: Vector,
    z: Vector,
    thresholds: Vector,
    *,
    run: int = 8,
    z_threshold: float = 4,
    exempt: set[int] | None = None,
) -> dict[str, Any]:
    excess = np.maximum(projections - thresholds, z - z_threshold)
    excess[~((projections > thresholds) | (z >= z_threshold))] = -np.inf
    if exempt:
        excess[:, sorted(exempt)] = -np.inf
    consecutive, last, maximum = 0, -1, 0
    flagged: set[int] = set()
    token_alarms = 0
    for scores in excess:
        concept = int(np.argmax(scores)) if scores.max() >= 0 else -1
        token_alarms += int(concept >= 0)
        consecutive = consecutive + 1 if concept == last and concept >= 0 else int(concept >= 0)
        maximum = max(maximum, consecutive)
        if consecutive >= run:
            flagged.add(concept)
        last = concept
    return {
        "any_alarm": float(bool(flagged)),
        "flagged": flagged,
        "max_run": maximum,
        "token_alarm": token_alarms / len(z) if len(z) else 0.0,
    }
