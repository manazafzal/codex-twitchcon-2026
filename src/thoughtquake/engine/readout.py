from collections import deque
from dataclasses import dataclass

import numpy as np

from thoughtquake.concepts.library import ConceptLibrary
from thoughtquake.engine.immune import unit
from thoughtquake.model.backend import Vector


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
        self.window = deque(maxlen=window)
        self.margin_threshold = margin_threshold

    def reset(self) -> None:
        self.window.clear()

    def observe(self, hidden: Vector, active: list[str], secret: str | None = None) -> Reading:
        self.window.append(np.asarray(hidden).copy())
        mean = np.mean(self.window, axis=0) - self.library.HR_neutral
        cosines = unit(self.library.D) @ unit(mean)
        scores = dict(zip(self.library.ids, map(float, cosines), strict=True))
        candidates = set(active) | ({secret} if secret else set())
        ranking = sorted((f for f in candidates if f in scores), key=lambda f: (-scores[f], f))
        top = ranking[0] if ranking else None
        margin = scores[top] - (scores[ranking[1]] if len(ranking) > 1 else 0) if top else 0.0
        color = top if margin >= self.margin_threshold and np.linalg.norm(mean) > 0 else None
        return Reading(scores, top, margin, color)
