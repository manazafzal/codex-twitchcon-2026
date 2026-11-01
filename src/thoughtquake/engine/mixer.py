import math
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from thoughtquake.engine.events import Push, Tick
from thoughtquake.engine.immune import unit
from thoughtquake.model.backend import Vector

ScheduleMode = Literal["answer", "sentence", "token"]
NEUTRAL = "Neutral"


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Clock cannot go backwards")
        self.now += seconds


class Mixer:
    def __init__(
        self,
        *,
        half_life: float = 20,
        kappa: float = 3,
        dominance_cap: float = 0.75,
        beta_max: float = 1.5,
        schedule_mode: ScheduleMode = "answer",
        chunk: int = 16,
        inject_scale: float = 10,
        clock: Callable[[], float] = time.monotonic,
        alpha: float | None = None,
        median_norm: float = 26.78,
    ) -> None:
        if half_life <= 0 or kappa <= 0 or not 0 < dominance_cap <= 0.75:
            raise ValueError("Invalid mixer parameters")
        if not 0 <= beta_max <= 2 or inject_scale < 0 or chunk < 1:
            raise ValueError("Invalid injection strength or chunk")
        if schedule_mode not in {"answer", "sentence", "token"}:
            raise ValueError("Invalid schedule mode")
        if alpha is not None and (not 0 <= alpha <= 0.5 or median_norm <= 0):
            raise ValueError("Invalid alpha or residual norm")
        self.alpha, self.median_norm = alpha, median_norm
        self.half_life, self.kappa = half_life, kappa
        self.dominance_cap, self.beta_max = dominance_cap, beta_max
        self.schedule_mode, self.chunk = schedule_mode, chunk
        self.inject_scale, self.clock = inject_scale, clock
        self._history: dict[str, list[float]] = defaultdict(list)
        self._doses: dict[str, float] = defaultdict(float)
        self._users: dict[str, float] = defaultdict(float)
        self._last = clock()
        self._selected: str | None = None
        self._beta = 0.0

    def _decay(self, now: float) -> None:
        if now < self._last:
            raise ValueError("Pushes and clock must be chronological")
        decay = 2 ** (-(now - self._last) / self.half_life)
        for values in (self._doses, self._users):
            for key in values:
                values[key] *= decay
        self._last = now

    def push(self, event: Push) -> float:
        if event.faction == NEUTRAL:
            raise ValueError("Neutral is reserved")
        self._decay(event.t)
        recent = [t for t in self._history[event.user_id or event.user] if event.t - t < 20]
        self._history[event.user_id or event.user] = recent
        if len(recent) >= 3:
            return 0.0
        weight = 0.25 if any(event.t - t < 8 for t in recent) else 1.0
        recent.append(event.t)
        self._doses[event.faction] += weight
        self._users[event.user] += weight
        return weight

    def tick(self) -> Tick:
        now = self.clock()
        self._decay(now)
        top = sorted(self._doses.items(), key=lambda item: (-item[1], item[0]))[:3]
        total = sum(dose for _, dose in top)
        # Quiet-chat Neutral is reserved first; cap excess also goes to Neutral.
        activity = min(1.0, total / self.kappa)
        shares = {
            f: min(self.dominance_cap, dose / total) * activity for f, dose in top if total > 0
        }
        shares[NEUTRAL] = max(0.0, 1 - sum(shares.values()))
        beta = self.beta_max * (1 - math.exp(-total / self.kappa))
        users = sorted(self._users.items(), key=lambda item: (-item[1], item[0]))[:5]
        return Tick(shares, beta, users, now)

    def select(self, index: int, rng: np.random.Generator) -> str | None:
        redraw = (
            index == 0
            or self.schedule_mode == "token"
            or (self.schedule_mode == "sentence" and index % self.chunk == 0)
        )
        if redraw:
            tick = self.tick()
            names = list(tick.shares)
            picked = str(rng.choice(names, p=list(tick.shares.values())))
            self._selected = None if picked == NEUTRAL else picked
            self._beta = tick.beta
        return self._selected

    def vector(self, vectors: dict[str, Vector]) -> Vector | None:
        if self._selected is None:
            return None
        strength = (
            self.alpha * self.median_norm * self._beta / self.beta_max
            if self.alpha is not None and self.beta_max
            else self.inject_scale * self._beta
        )
        return unit(vectors[self._selected]) * strength

    @property
    def selected(self) -> str | None:
        return self._selected

    @property
    def last_time(self) -> float:
        return self._last

    def hold(self, faction: str | None, beta: float) -> None:
        self._selected, self._beta = faction, beta


class ForcedMixer(Mixer):
    """Evaluation holds the target independently of the capped public contest shares."""

    def __init__(
        self,
        faction: str,
        *,
        alpha: float,
        median_norm: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(alpha=alpha, median_norm=median_norm, beta_max=1, clock=clock)
        self.faction = faction

    def select(self, index: int, rng: np.random.Generator) -> str:
        self.hold(self.faction, self.tick().beta)
        return self.faction
