from collections import deque
from dataclasses import dataclass

import numpy as np

from nous.concepts.library import ConceptLibrary
from nous.concepts.probe import lda_scores
from nous.engine.immune import unit
from nous.model.backend import Vector


@dataclass(frozen=True)
class Reading:
    scores: dict[str, float]
    top: str | None
    margin: float
    color: str | None


class Readout:
    def __init__(
        self, library: ConceptLibrary, *, window: int = 12, margin_threshold: float = 0.1
    ) -> None:
        if window < 1 or margin_threshold < 0:
            raise ValueError("Invalid readout parameters")
        self.library = library
        self.window: deque[Vector] = deque(maxlen=window)
        self.layer_window: deque[dict[int, Vector]] = deque(maxlen=window)
        self.margin_threshold = margin_threshold

    def reset(self) -> None:
        self.window.clear()
        self.layer_window.clear()

    def features(self, layers: list[dict[int, Vector]]) -> Vector | None:
        wanted = self.library.config.get("probe_layers", [16, 20, 22])
        if not layers or any(any(layer not in item for layer in wanted) for item in layers):
            return None
        return np.concatenate(
            [np.mean([item[layer] for item in layers], axis=0) for layer in wanted]
        )

    def observe(
        self,
        hidden: Vector,
        active: list[str],
        secret: str | None = None,
        layers: dict[int, Vector] | None = None,
    ) -> Reading:
        self.window.append(np.asarray(hidden).copy())
        self.layer_window.append(layers or {})
        mean = np.mean(self.window, axis=0) - self.library.HR_neutral
        return self.decide(
            mean + self.library.HR_neutral,
            active,
            secret,
            features=self.features(list(self.layer_window)),
        )

    def decide(
        self,
        hidden: Vector,
        active: list[str],
        secret: str | None = None,
        *,
        features: Vector | None = None,
    ) -> Reading:
        mean = np.asarray(hidden) - self.library.HR_neutral
        cosines = unit(self.library.D) @ unit(mean)
        if self.library.readout_mean is not None and self.library.readout_std is not None:
            cosines = (cosines - self.library.readout_mean) / self.library.readout_std
        scores = dict(zip(self.library.ids, map(float, cosines), strict=True))
        labels = scores
        if features is not None and self.library.readout_v4:
            values = lda_scores(self.library.readout_v4, features)
            labels = dict(zip(self.library.ids, map(float, values), strict=True))
        valid = bool(np.linalg.norm(mean)) or (
            features is not None and bool(self.library.readout_v4)
        )
        ranking = sorted(labels, key=lambda f: (-labels[f], f)) if valid else []
        top = ranking[0] if ranking else None
        margin = labels[top] - (labels[ranking[1]] if len(ranking) > 1 else 0) if top else 0.0
        color = top if margin >= self.margin_threshold and valid else None
        return Reading(scores, top, margin, color)
