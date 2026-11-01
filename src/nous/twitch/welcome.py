"""Small, bounded welcome queue; only the real chat sender decides when a message is sent."""

import time
from collections import OrderedDict, deque
from collections.abc import Callable

from nous.concepts.library import Concept, concept_pattern


class Welcomes:
    def __init__(
        self, concepts: list[Concept], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.clock = clock
        self.labels = {c.id: c.label for c in concepts}
        self.patterns = [concept_pattern(c, stems=True) for c in concepts]
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.pending: deque[tuple[str, str]] = deque()
        self.last = float("-inf")
        self.variant = 0

    def offer(self, user_id: str, name: str, team: str) -> None:
        if user_id in self.seen or len(self.pending) >= 8:
            return
        self.seen[user_id] = None
        if len(self.seen) > 10000:
            self.seen.popitem(last=False)
        self.pending.append((name[:25], team))

    def take(self, *, blind: bool) -> str | None:
        if not self.pending or self.clock() - self.last < 10:
            return None
        name, team = self.pending.popleft()
        if blind:
            for pattern in self.patterns:
                name = pattern.sub("Friend", name)
            suggestion = "You're in! Try !guess <word>."
        elif team in self.labels:
            suggestion = f"Team {self.labels[team]}! Try !push {team}."
        else:
            suggestion = "Glad you're here. Try !join."
        openings = (f"Hi {name}!", f"Welcome, {name}!", f"Hey {name}, nice to see you!")
        message = openings[self.variant % len(openings)] + " " + suggestion
        self.variant += 1
        self.last = self.clock()
        return message[:200]
