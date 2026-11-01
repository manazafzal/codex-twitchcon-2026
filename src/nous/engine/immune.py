from dataclasses import dataclass, field

import numpy as np

from nous.model.backend import DefendSpec, Vector


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


@dataclass(frozen=True)
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
        token_reductions = []
        for concept, before, after, threshold in zip(concepts, pre, post, thresholds, strict=True):
            fired = before > threshold
            self.consecutive[concept] = self.consecutive.get(concept, 0) + 1 if fired else 0
            if fired and before != 0:
                token_reductions.append(float(1 - after / before))
            if self.consecutive[concept] >= 3:
                detected.append(concept)
        if (
            readout_top
            and margin >= margin_threshold
            and readout_top not in (pushed or set())
            and readout_top not in detected
        ):
            detected.append(readout_top)
        self.reductions.append(float(np.mean(token_reductions)) if token_reductions else 0.0)
        mean = float(np.mean(self.reductions)) if self.reductions else 0.0
        return ImmuneDecision(tuple(detected), mean)


ALARM_RUN = 8


@dataclass(frozen=True)
class Alarm:
    concept: str | None
    token_alarm: bool
    fired: bool
    neutralised: float


class AlarmMonitor:
    """Detection uses independent thresholds; a successful clamp alone is not an alarm."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last: str | None = None
        self.run = 0
        self.max_run = 0
        self.reductions: list[float] = []

    def observe(
        self,
        concepts: tuple[str, ...],
        pre: Vector,
        post: Vector,
        thresholds: Vector,
        z: dict[str, float],
        *,
        exempt: set[str],
    ) -> Alarm:
        candidates = [
            (max(float(projection - threshold), z.get(concept, 0) - 4), concept)
            for concept, projection, threshold in zip(concepts, pre, thresholds, strict=True)
            if concept not in exempt and (projection > threshold or z.get(concept, 0) >= 4)
        ]
        concept = max(candidates)[1] if candidates else None
        self.run = (
            self.run + 1
            if concept is not None and concept == self.last
            else int(concept is not None)
        )
        self.last = concept
        self.max_run = max(self.max_run, self.run)
        changed = pre > post
        reductions = 1 - post[changed] / np.maximum(np.abs(pre[changed]), 1e-8)
        self.reductions.append(float(np.mean(np.clip(reductions, 0, 1))) if len(reductions) else 0)
        return Alarm(
            concept, bool(candidates), self.run >= ALARM_RUN, float(np.mean(self.reductions))
        )
