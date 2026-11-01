"""Bounded proposals wait for the engine owner's next safe boundary."""

import logging
from collections import OrderedDict, deque
from pathlib import Path

from nous.concepts.policy import validate_name
from nous.concepts.topics import BuildResult, TopicBuilder, approved, save_result, unavailable


class TopicQueue:
    def __init__(self, directory: Path, builder: TopicBuilder | None = None) -> None:
        self.directory, self.builder = directory, builder
        self.pending: deque[str] = deque()
        self.users: OrderedDict[str, float] = OrderedDict()
        self.last = float("-inf")
        self.added = 0
        self.active: str | None = None

    def offer(self, name: str, user: str, now: float, known: set[str]) -> bool:
        try:
            validate_name(name, chat=True)
        except ValueError:
            return False
        if (
            name in known
            or name == self.active
            or name in self.pending
            or len(self.pending) >= 8
            or self.added >= 5
            or now - self.users.get(user, float("-inf")) < 300
            or now - self.last < 15
        ):
            return False
        self.users[user], self.last = now, now
        self.users.move_to_end(user)
        if len(self.users) > 4096:
            self.users.popitem(last=False)
        self.pending.append(name)
        return True

    def build(self, name: str) -> BuildResult:
        try:
            result = (
                self.builder.build(name)
                if self.builder
                else BuildResult(
                    unavailable(name, "A prepared local model and library are required")
                )
            )
            save_result(result, self.directory / name)
            return result
        except Exception:  # noqa: BLE001 - a failed private build must not restart the live engine
            logging.getLogger(__name__).error(
                "Topic build or local report failed; keeping the current catalog"
            )
            return BuildResult(
                unavailable(name, "Local testing could not finish; the topic stays private")
            )

    def accept(self, result: BuildResult) -> None:
        if not approved(result) or self.added >= 5:
            return
        assert result.library is not None
        if self.builder and result.report.get("base_hash") != self.builder.base.hash:
            raise ValueError("The base library changed during testing")
        result.library.save(self.directory.parent / "concepts.npz")
        if self.builder:
            self.builder = TopicBuilder(
                self.builder.backend, result.library, seed=self.builder.seed
            )
        self.added += 1

    def build_next(self) -> BuildResult:
        result = self.build(self.pending.popleft())
        self.accept(result)
        return result
