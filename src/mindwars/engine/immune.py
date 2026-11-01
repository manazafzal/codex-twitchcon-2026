from dataclasses import dataclass, field

import numpy as np

from mindwars.model.backend import DefendSpec, Vector


def unit(vector: Vector) -> Vector:
    value = np.asarray(vector, dtype=float)
    norms = np.linalg.norm(value, axis=-1, keepdims=True)
    return np.divide(value, norms, out=np.zeros_like(value), where=norms > 0)


def clamp(hidden: Vector, spec: DefendSpec) -> tuple[Vector, Vector, Vector]:
    """Apply the oracle projection clamp, preserving components orthogonal to its span."""
    directions = unit(spec.directions)
    result = np.array(hidden, dtype=float, copy=True)
    pre = result @ directions.T
    for direction, threshold in zip(directions, spec.thresholds, strict=True):
        excess = np.maximum(result @ direction - threshold, 0)
        result -= np.expand_dims(excess, -1) * direction
    return result, pre, result @ directions.T


@dataclass
class ImmuneDecision:
    concepts: tuple[str, ...]
    neutralised: float


@dataclass
class ImmuneMonitor:
    consecutive: dict[str, int] = field(default_factory=dict)
    reductions: list[float] = field(default_factory=list)

    def reset(self) -> None:
        self.consecutive.clear()
        self.reductions.clear()

    def observe(
        self,
        concepts: tuple[str, ...],
        pre: Vector,
        post: Vector,
        thresholds: Vector,
        *,
        readout_top: str | None = None,
        margin: float = 0,
        margin_threshold: float = float("inf"),
        pushed: set[str] | None = None,
    ) -> ImmuneDecision:
        detected = []
        for concept, before, after, threshold in zip(concepts, pre, post, thresholds, strict=True):
            fired = before > threshold
            self.consecutive[concept] = self.consecutive.get(concept, 0) + 1 if fired else 0
            self.reductions.append(float(1 - after / before) if before != 0 else 0.0)
            if self.consecutive[concept] >= 3:
                detected.append(concept)
        if (
            readout_top
            and margin >= margin_threshold
            and readout_top not in (pushed or set())
            and readout_top not in detected
        ):
            detected.append(readout_top)
        mean = float(np.mean(self.reductions)) if self.reductions else 0.0
        return ImmuneDecision(tuple(detected), mean)
