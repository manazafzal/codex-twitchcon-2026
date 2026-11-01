"""Bounded round points use accepted input and the answer's measured concept hits."""

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from nous.server.leaderboard import Leaderboard


@dataclass(frozen=True)
class Award:
    viewer: str
    name: str
    points: float
    reason: str


class Scoring:
    def __init__(
        self, leaderboard: Leaderboard | None = None, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.board = leaderboard or Leaderboard()
        self.clock = clock
        self.cooldowns: dict[tuple[str, str], float] = {}
        self.round = -1
        self.begin(0)

    def begin(self, number: int) -> None:
        self.round = number
        self.pushes: dict[str, dict[str, float]] = defaultdict(dict)
        self.names: dict[str, str] = {}
        self.attempts: dict[tuple[str, str], int] = defaultdict(int)
        self.round_points: dict[str, float] = defaultdict(float)
        self.correct: set[str] = set()
        self.catches: set[str] = set()
        self.awards: list[Award] = []
        self.closed = False

    def allow(
        self,
        viewer: str,
        kind: str,
        *,
        cooldown: float,
        maximum: int,
        at: float | None = None,
    ) -> bool:
        key = (viewer, kind)
        now = self.clock() if at is None else at
        if (
            self.closed
            or self.attempts[key] >= maximum
            or now - self.cooldowns.get(key, float("-inf")) < cooldown
        ):
            return False
        self.attempts[key] += 1
        self.cooldowns[key] = now
        return True

    def push(
        self,
        viewer: str,
        name: str,
        faction: str,
        weight: float,
        *,
        at: float | None = None,
    ) -> bool:
        if weight <= 0 or not self.allow(viewer, "push", cooldown=1, maximum=3, at=at):
            return False
        self.names[viewer] = name
        group = self.pushes[faction]
        group[viewer] = group.get(viewer, 0) + min(weight, 1)
        return True

    def award(
        self, viewer: str, name: str, points: float, reason: str, faction: str | None = None
    ) -> float:
        points = max(0, min(points, 120 - self.round_points[viewer]))
        if points:
            self.round_points[viewer] += points
            self.names[viewer] = name
            self.board.add(viewer, name, points, faction)
            self.awards.append(Award(viewer, name, points, reason))
        return points

    def guess(
        self,
        viewer: str,
        name: str,
        *,
        correct: bool,
        at: float | None = None,
    ) -> float:
        if (
            viewer in self.correct
            or not self.allow(viewer, "guess", cooldown=2, maximum=3, at=at)
            or not correct
        ):
            return 0
        prizes = (100, 60, 40, 25, 15, 10)
        points = prizes[min(len(self.correct), len(prizes) - 1)]
        self.correct.add(viewer)
        return self.award(viewer, name, points, "guess")

    def catch(
        self,
        viewer: str,
        name: str,
        *,
        true_concept: str | None,
        attributed: tuple[str, ...],
        immune: bool,
    ) -> float:
        if self.closed or viewer in self.catches or not immune or true_concept not in attributed:
            return 0
        self.catches.add(viewer)
        return self.award(viewer, name, 15, "immune")

    def finish(self, hits: dict[str, float]) -> Award | None:
        if self.closed:
            return self.mvp
        total = sum(sum(group.values()) for group in self.pushes.values())
        for faction, group in self.pushes.items():
            dose = sum(group.values())
            if total and dose:
                budget = 20 * max(0, min(1, hits.get(faction, 0))) * dose / total
                for viewer, weight in group.items():
                    self.award(viewer, self.names[viewer], budget * weight / dose, "push", faction)
        self.closed = True
        self.board.save()
        return self.mvp

    @property
    def mvp(self) -> Award | None:
        if not self.round_points or max(self.round_points.values()) <= 0:
            return None
        viewer = min(self.round_points, key=lambda key: (-self.round_points[key], key))
        return Award(viewer, self.names[viewer], self.round_points[viewer], "round")
