from dataclasses import replace

import numpy as np

from thoughtquake.engine.events import Push, Tick
from thoughtquake.engine.immune import unit
from thoughtquake.engine.mixer import Mixer
from thoughtquake.model.backend import Vector


class FixedInjection(Mixer):
    """A comparison or secret round holds one injection while war doses stay separate."""

    def __init__(self, war: Mixer, faction: str, *, beta: float = 2.0) -> None:
        super().__init__(
            clock=war.clock,
            inject_scale=war.inject_scale,
            alpha=war.alpha,
            median_norm=war.median_norm,
            beta_max=war.beta_max,
        )
        if not 0 <= beta <= 2:
            raise ValueError("Round strength must be between zero and two")
        self.war, self.faction, self.strength = war, faction, beta

    def select(self, index: int, rng: np.random.Generator) -> str:
        self.hold(self.faction, self.strength)
        return self.faction

    def vector(self, vectors: dict[str, Vector]) -> Vector:
        strength = (
            self.alpha * self.median_norm * self.strength / 2
            if self.alpha is not None
            else self.inject_scale * self.strength
        )
        return unit(vectors[self.faction]) * strength

    def tick(self) -> Tick:
        return replace(self.war.tick(), beta=self.strength)

    def push(self, event: Push) -> float:
        return self.war.push(event)
