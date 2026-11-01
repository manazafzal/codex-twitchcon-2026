from dataclasses import dataclass
from typing import TypeAlias

from nous.engine.events import Control, Guess, Push


@dataclass(frozen=True)
class SetMode:
    mode: str


@dataclass(frozen=True)
class Rank:
    user: str
    user_id: str


@dataclass(frozen=True)
class StartRound:
    user: str = "broadcaster"
    user_id: str | None = None
    source: str = "LOCAL"


@dataclass(frozen=True)
class Participation:
    push: Push
    passive: bool = True


@dataclass(frozen=True)
class Propose:
    name: str
    user: str
    user_id: str


Command: TypeAlias = Propose | Push | SetMode | Control | Guess | Rank | StartRound | Participation
