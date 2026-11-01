import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from nous.concepts.library import Concept, match_concept


class Phase(StrEnum):
    IDLE = "idle"
    ARMED = "armed"
    GENERATING = "generating"
    GUESSING = "guessing"
    REVEAL = "reveal"


@dataclass
class Score:
    name: str
    points: int = 0


class Telepathy:
    """Keep game decisions independent of model calls, sockets, and rendering."""

    def __init__(
        self,
        concepts: list[Concept],
        *,
        clock: Callable[[], float] = time.monotonic,
        seed: int = 0,
        seconds: float = 30,
    ) -> None:
        if seconds <= 0:
            raise ValueError("Guessing time must be positive")
        self.concepts, self.clock, self.seconds = concepts, clock, seconds
        self.rng = np.random.default_rng(seed)
        self.phase = Phase.IDLE
        self.secret: str | None = None
        self.winner: str | None = None
        self.probe_top: str | None = None
        self.candidates: tuple[str, ...] = ()
        self.deadline: float | None = None
        self.started_at: float | None = None
        self.scores: dict[str, Score] = {}
        self.round_id = 0

    def arm(self, active: set[str], *, secret: str | None = None) -> str:
        if self.phase != Phase.IDLE:
            raise ValueError("Finish the current Telepathy round before arming")
        choices = [c.id for c in self.concepts if c.id not in active]
        if not choices or (secret is not None and secret not in choices):
            raise ValueError("Telepathy needs a library concept outside the active war")
        self.secret = secret or str(self.rng.choice(choices))
        self.winner = self.probe_top = self.deadline = None
        self.candidates = ()
        self.started_at = None
        self.round_id += 1
        self.phase = Phase.ARMED
        return self.secret

    def start(self) -> None:
        if self.phase != Phase.ARMED:
            raise ValueError("Arm Telepathy before generation")
        self.phase = Phase.GENERATING

    def finish_generation(self, scores: dict[str, float]) -> None:
        if self.phase != Phase.GENERATING:
            raise ValueError("Telepathy is not generating")
        known = {c.id for c in self.concepts}
        ranked = sorted((c for c in scores if c in known), key=lambda c: (-scores[c], c))
        self.candidates = tuple(ranked[:3])
        self.probe_top = ranked[0] if ranked else None
        self.started_at = self.clock()
        self.deadline = self.started_at + self.seconds
        self.phase = Phase.GUESSING

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - self.clock()) if self.phase == Phase.GUESSING else 0.0

    def tick(self, at: float | None = None) -> Phase:
        now = self.clock() if at is None else at
        if self.phase == Phase.GUESSING and now >= self.deadline:
            self.phase = Phase.REVEAL
        return self.phase

    def guess(
        self, user: str, word: str, *, user_id: str | None = None, at: float | None = None
    ) -> bool:
        if self.tick(at) != Phase.GUESSING:
            return False
        if at is not None and at < self.started_at:
            return False
        if match_concept(word, self.concepts) != self.secret:
            return False
        key = user_id or user
        score = self.scores.setdefault(key, Score(user))
        score.name, score.points = user, score.points + 1
        self.winner = user
        self.phase = Phase.REVEAL
        return True

    @property
    def scoreboard(self) -> tuple[tuple[str, int], ...]:
        ranked = sorted(
            self.scores.items(),
            key=lambda item: (-item[1].points, item[1].name.casefold(), item[0]),
        )
        return tuple((score.name, score.points) for _, score in ranked[:5])

    def reset(self) -> None:
        if self.phase != Phase.REVEAL:
            raise ValueError("Reveal the answer before returning to idle")
        self.cancel()

    def cancel(self) -> None:
        self.phase = Phase.IDLE
        self.secret = self.winner = self.probe_top = self.deadline = None
        self.candidates = ()
        self.started_at = None
