"""Training-only transforms and validation-only regularization selection."""

from dataclasses import dataclass
from typing import Any

import numpy as np

from nous.concepts.probe import Example, check_partitions
from nous.model.backend import Vector
from nous.research.vectors import inverse_root


@dataclass(frozen=True)
class Classifier:
    center: Vector
    transform: Vector
    weights: Vector
    bias: Vector
    regularization: float
    validation_accuracy: float

    def scores(self, x: Vector) -> Vector:
        centered = x - self.center
        scaled = (
            centered * self.transform if self.transform.ndim == 1 else centered @ self.transform
        )
        return scaled @ self.weights.T + self.bias


def fit_candidate(
    x: Vector, y: Vector, classes: int, kind: str, reg: float
) -> tuple[Vector, Vector]:
    means = np.stack([x[y == i].mean(axis=0) for i in range(classes)])
    if kind == "lda":
        residual = x - means[y.astype(int)]
        target = max(float(np.sum(residual**2) / (max(1, len(x) - classes) * x.shape[1])), 1e-6)
        u = residual * np.sqrt((1 - reg) / max(1, len(x) - classes))
        diagonal = reg * target
        if x.shape[1] > len(x):
            base = means.T / diagonal
            weights = (
                base
                - u.T @ np.linalg.solve(np.eye(len(x)) + u @ u.T / diagonal, u @ base) / diagonal
            ).T
        else:
            weights = np.linalg.solve(u.T @ u + np.eye(x.shape[1]) * diagonal, means.T).T
        return weights, -0.5 * np.sum(means * weights, axis=1)
    if kind != "logistic":
        raise ValueError("Unknown classifier")
    weights, bias = np.zeros_like(means), np.zeros(classes)
    targets = np.eye(classes)[y.astype(int)]
    # Fixed full-batch updates are deterministic; no test-set stopping rule.
    step = 1 / (np.linalg.norm(x, 2) ** 2 / len(x) + reg + 1)
    for _ in range(600):
        scores = x @ weights.T + bias
        p = np.exp(scores - scores.max(axis=1, keepdims=True))
        error = p / p.sum(axis=1, keepdims=True) - targets
        weights -= step * (error.T @ x / len(x) + reg * weights)
        bias -= step * error.mean(axis=0)
    return weights, bias


def fit_variant(
    train: list[Example],
    validation: list[Example],
    test: list[Example],
    ids: tuple[str, ...],
    hidden_size: int,
    variant: dict[str, Any],
) -> Classifier:
    check_partitions(train, validation, test)
    selected = [
        e for key in ids for e in [t for t in train if t.concept == key][: variant["train_size"]]
    ]
    if len(selected) != variant["train_size"] * len(ids):
        raise ValueError("Incomplete balanced training set")
    indices = np.concatenate(
        [
            np.arange(
                [16, 20, 22].index(i) * hidden_size, ([16, 20, 22].index(i) + 1) * hidden_size
            )
            for i in variant["layers"]
        ]
    )
    x = np.stack([e.features[indices] for e in selected])
    val = np.stack([e.features[indices] for e in validation])
    center = x.mean(axis=0)
    transform: Vector
    if variant["whitening"] == "none":
        transform = np.ones(x.shape[1])
    elif variant["whitening"] == "standardize":
        transform = 1 / np.maximum(x.std(axis=0), 1e-6)
    elif variant["whitening"] == "zca":
        transform = inverse_root(np.atleast_2d(np.cov(x, rowvar=False)))
    else:
        raise ValueError("Unknown whitening transform")
    x, val = (
        ((x - center) * transform, (val - center) * transform)
        if transform.ndim == 1
        else ((x - center) @ transform, (val - center) @ transform)
    )
    labels = np.array([ids.index(e.concept) for e in selected])
    truth = np.array([ids.index(e.concept) for e in validation])
    options = [0.05, 0.2, 0.5] if variant["classifier"] == "lda" else [0.01, 0.1, 1.0]
    candidates = []
    for reg in options:
        weights, bias = fit_candidate(x, labels, len(ids), variant["classifier"], reg)
        accuracy = float(np.mean(np.argmax(val @ weights.T + bias, axis=1) == truth))
        candidates.append(Classifier(center, transform, weights, bias, reg, accuracy))
    return max(candidates, key=lambda c: (c.validation_accuracy, c.regularization))


def features(full: Vector, hidden_size: int, layers: list[int]) -> Vector:
    return np.concatenate(
        [
            full[
                [16, 20, 22].index(layer) * hidden_size : ([16, 20, 22].index(layer) + 1)
                * hidden_size
            ]
            for layer in layers
        ]
    )
