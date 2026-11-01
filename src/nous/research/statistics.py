"""Resample whole concepts, retaining matched answers within each selected cluster."""

from collections.abc import Mapping
from typing import Any

import numpy as np

from nous.evaluation import wilson

Key = tuple[str, str, int]


def summary(
    values: Mapping[Key, float],
    *,
    seed: int = 0,
    resamples: int = 2000,
    binary: bool = True,
) -> dict[str, Any]:
    if resamples < 2 or not all(np.isfinite(v) for v in values.values()):
        raise ValueError("Finite observations and at least two resamples required")
    concepts = sorted({key[0] for key in values})
    if not concepts:
        return {"n": 0, "clusters": 0, "mean": None, "cluster_ci95": None, "wilson95": None}
    groups = [np.array([v for k, v in sorted(values.items()) if k[0] == c]) for c in concepts]
    totals = np.array([[g.sum(), len(g)] for g in groups])
    draws = np.random.default_rng(seed).integers(0, len(groups), (resamples, len(groups)))
    sampled = totals[draws].sum(axis=1)
    ratios = sampled[:, 0] / sampled[:, 1]
    total, n = totals.sum(axis=0)
    return {
        "n": int(n),
        "clusters": len(groups),
        "mean": float(total / n),
        "cluster_ci95": np.percentile(ratios, [2.5, 97.5]).tolist(),
        "wilson95": wilson(float(total), float(n)) if binary else None,
    }


def paired(
    left: Mapping[Key, float],
    right: Mapping[Key, float],
    *,
    seed: int = 0,
    resamples: int = 2000,
) -> dict[str, Any]:
    if not left or left.keys() != right.keys():
        raise ValueError("Paired comparisons require identical nonempty answer keys")
    return summary(
        {k: left[k] - right[k] for k in left}, seed=seed, resamples=resamples, binary=False
    )


def reduction(
    off: Mapping[Key, float],
    on: Mapping[Key, float],
    *,
    seed: int = 0,
    resamples: int = 2000,
) -> dict[str, Any]:
    if not off or off.keys() != on.keys():
        raise ValueError("Reduction requires matched nonempty answers")
    keys = sorted({k[0] for k in off})
    sums = np.array([[sum(v for k, v in x.items() if k[0] == c) for x in (off, on)] for c in keys])
    totals = sums.sum(axis=0)
    draws = np.random.default_rng(seed).integers(0, len(keys), (resamples, len(keys)))
    boot = sums[draws].sum(axis=1)
    # A zero-hit control leaves the relative effect undefined, never a successful reduction.
    valid = boot[:, 0] > 0
    return {
        "n": len(off),
        "clusters": len(keys),
        "mean": float(1 - totals[1] / totals[0]) if totals[0] else None,
        "cluster_ci95": np.percentile(1 - boot[valid, 1] / boot[valid, 0], [2.5, 97.5]).tolist()
        if valid.all()
        else None,
        "undefined_resamples": int((~valid).sum()),
    }
