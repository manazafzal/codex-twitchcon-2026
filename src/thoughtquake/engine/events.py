from dataclasses import asdict, dataclass, field
from typing import Any, Literal


class Event:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Push(Event):
    user: str
    faction: str
    t: float
    source: str
    kind: Literal["push"] = field(default="push", init=False)


@dataclass(frozen=True)
class Tick(Event):
    shares: dict[str, float]
    beta: float
    top_pushers: list[tuple[str, float]]
    t: float
    kind: Literal["tick"] = field(default="tick", init=False)


@dataclass(frozen=True)
class Token(Event):
    i: int
    text: str
    applied: str | None
    readout: dict[str, Any]
    color: str | None
    kind: Literal["token"] = field(default="token", init=False)


@dataclass(frozen=True)
class Mode(Event):
    mode: str
    immune: bool
    prompt: str
    answer: int
    kind: Literal["mode"] = field(default="mode", init=False)


@dataclass(frozen=True)
class Tamper(Event):
    concepts: tuple[str, ...]
    neutralised: float
    kind: Literal["tamper"] = field(default="tamper", init=False)


@dataclass(frozen=True)
class Badge(Event):
    label: str
    kind: Literal["badge"] = field(default="badge", init=False)
