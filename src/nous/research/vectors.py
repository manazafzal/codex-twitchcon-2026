"""Vector constructions share texts, seeds and normalization across conditions."""

import numpy as np

from nous.engine.immune import unit
from nous.model.backend import Vector


def inverse_root(covariance: Vector, shrinkage: float = 0.2) -> Vector:
    target = max(float(np.trace(covariance) / len(covariance)), 1e-6)
    values, axes = np.linalg.eigh(
        (1 - shrinkage) * covariance + shrinkage * target * np.eye(len(covariance))
    )
    return (axes * (1 / np.sqrt(np.maximum(values, 1e-8)))) @ axes.T


def construct(
    means: Vector,
    neutral: Vector,
    paired: Vector,
    covariance: Vector,
    method: str,
    *,
    seed: int,
) -> Vector:
    values: Vector
    if method == "others":
        values = means - (means.sum(axis=0) - means) / (len(means) - 1)
    elif method == "neutral":
        values = means - neutral
    elif method == "raw":
        values = means
    elif method == "paired":
        values = means - paired
    elif method == "whitened":
        values = (means - neutral) @ inverse_root(covariance)
    elif method == "random":
        values = np.random.default_rng(seed).normal(size=means.shape)
    else:
        raise ValueError("Unknown vector construction")
    return unit(values)
