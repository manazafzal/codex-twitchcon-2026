"""Small shrinkage LDA fit with explicit, auditable family and seed partitions."""

import hashlib
from dataclasses import dataclass

import numpy as np

from nous.model.backend import Vector


@dataclass(frozen=True)
class Example:
    text: str
    concept: str
    family: str
    seed: int
    features: Vector
    mode: str = "text"


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()


def check_partitions(train: list[Example], validation: list[Example], test: list[Example]) -> None:
    parts = (train, validation, test)
    if any(not part for part in parts):
        raise ValueError("Train, validation and test partitions must be nonempty")
    for i, left in enumerate(parts):
        for right in parts[i + 1 :]:
            for values in (lambda e: e.family, lambda e: e.seed, lambda e: text_hash(e.text)):
                if {values(e) for e in left} & {values(e) for e in right}:
                    raise ValueError("Readout partitions overlap in family, seed or text hash")


def fit_lda(
    examples: list[Example], ids: tuple[str, ...], shrinkage: float = 0.2
) -> dict[str, Vector]:
    if not 0 < shrinkage <= 1:
        raise ValueError("Shrinkage must be in (0,1]")
    x = np.stack([e.features for e in examples]).astype(float)
    center, scale = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-6)
    x = (x - center) / scale
    groups = [x[[e.concept == key for e in examples]] for key in ids]
    if any(len(group) < 2 for group in groups):
        raise ValueError("Each readout class requires at least two training answers")
    means = np.stack([group.mean(axis=0) for group in groups])
    residual = np.concatenate([group - mean for group, mean in zip(groups, means, strict=True)])
    # A diagonal target and a dual solve avoid allocating a dense multi-layer covariance.
    denominator = max(1, len(x) - len(ids))
    target = max(float(np.sum(residual**2) / (denominator * x.shape[1])), 1e-6)
    diagonal = shrinkage * target
    u = residual * np.sqrt((1 - shrinkage) / denominator)
    if x.shape[1] > len(x):
        inverse_means = means.T / diagonal
        correction = np.linalg.solve(np.eye(len(u)) + u @ u.T / diagonal, u @ inverse_means)
        weights = (inverse_means - u.T @ correction / diagonal).T
    else:
        covariance = u.T @ u + np.eye(x.shape[1]) * diagonal
        weights = np.linalg.solve(covariance, means.T).T
    intercept = -0.5 * np.sum(means * weights, axis=1) + np.log(
        np.array([len(g) for g in groups]) / len(x)
    )
    return {
        "center": center,
        "scale": scale,
        "weights": weights,
        "intercept": intercept,
        "shrinkage": np.array([shrinkage]),
    }


def lda_scores(parameters: dict[str, Vector], features: Vector) -> Vector:
    x = (features - parameters["center"]) / parameters["scale"]
    return parameters["weights"] @ x + parameters["intercept"]
