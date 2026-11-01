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


Command: TypeAlias = Push | SetMode | Control | Guess | Rank
