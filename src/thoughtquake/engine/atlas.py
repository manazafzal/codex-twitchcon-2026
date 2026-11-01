from collections import deque
from typing import Any

import numpy as np

from thoughtquake.concepts.library import ConceptLibrary
from thoughtquake.engine.immune import unit
from thoughtquake.model.backend import State, Vector


def pca_points(directions: Vector, ids: tuple[str, ...]) -> dict[str, list[float]]:
    centered = np.asarray(directions, dtype=float) - np.mean(directions, axis=0)
    _, _, axes = np.linalg.svd(centered, full_matrices=False)
    axes = axes[:2].copy()
    for axis in axes:
        if axis[np.argmax(np.abs(axis))] < 0:
            axis *= -1
    projected = centered @ axes.T
    if projected.shape[1] < 2:
        projected = np.pad(projected, ((0, 0), (0, 2 - projected.shape[1])))
    projected /= np.maximum(np.max(np.abs(projected), axis=0), 1e-12)
    return {name: list(map(float, point)) for name, point in zip(ids, projected, strict=True)}


class AtlasSignals:
    """Derive motion from measured token states; missing calibration never becomes an SD claim."""

    def __init__(self, library: ConceptLibrary) -> None:
        self.library = library
        self.points = pca_points(library.D, library.ids)
        self.previous: Vector | None = None
        self.previous_z: Vector | None = None
        self.residuals: deque[float] = deque(maxlen=60)

    def z(self, hidden: Vector) -> Vector:
        if self.library.readout_mean is None:
            return np.zeros(len(self.library.ids))
        cosine = unit(self.library.D) @ unit(hidden - self.library.HR_neutral)
        return (cosine - self.library.readout_mean) / self.library.readout_std

    def begin(self, hidden: Vector) -> None:
        self.previous, self.previous_z = hidden.copy(), self.z(hidden)
        self.residuals.clear()

    def observe(
        self, hidden: Vector, state: State, scores: dict[str, float] | None = None
    ) -> dict[str, Any]:
        z = self.z(hidden)
        if scores is not None and self.library.readout_mean is not None:
            cosine = np.array([scores[key] for key in self.library.ids])
            z = (cosine - self.library.readout_mean) / self.library.readout_std
        residual = (
            float(np.linalg.norm(hidden - self.previous)) if self.previous is not None else 0.0
        )
        self.residuals.append(residual)
        median = float(np.median(self.residuals))
        drive = min(1.0, residual / max(float(np.linalg.norm(hidden)), 1e-8))
        pulse = (
            np.clip((z - self.previous_z) / 6, 0, 1)
            if self.previous_z is not None
            else np.zeros_like(z)
        )
        clamp = 0.0
        if state.defence_pre is not None:
            clamp = min(
                1.0,
                float(np.linalg.norm(state.defence_pre - state.defence_post))
                / max(float(np.linalg.norm(state.defence_pre)), 1e-8),
            )
        self.previous, self.previous_z = hidden.copy(), z.copy()
        return {
            "z": dict(zip(self.library.ids, map(float, z), strict=True)),
            "pulse": dict(zip(self.library.ids, map(float, pulse), strict=True)),
            "residual": residual,
            "median": median,
            "drive": drive,
            "clamp": clamp,
            "calibrated": self.library.readout_mean is not None,
        }
