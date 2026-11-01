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
    user_id: str | None = None
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
    sky: dict[str, Any] | None = None
    kind: Literal["token"] = field(default="token", init=False)


@dataclass(frozen=True)
class Mode(Event):
    mode: str
    immune: bool
    prompt: str
    answer: int
    phase: str = "generating"
    remaining: float | None = None
    scoreboard: tuple[tuple[str, int], ...] = ()
    candidates: tuple[str, ...] = ()
    reveal: str | None = None
    panel: str = "main"
    colour_source: str = "applied"
    round_id: int | None = None
    winner: str | None = None
    probe_top: str | None = None
    probe_accuracy: float | None = None
    injection: str | None = None
    beta: float | None = None
    kind: Literal["mode"] = field(default="mode", init=False)


@dataclass(frozen=True)
class Tamper(Event):
    concepts: tuple[str, ...]
    neutralised: float
    kind: Literal["tamper"] = field(default="tamper", init=False)


@dataclass(frozen=True)
class Badge(Event):
    label: str
    quality: str | None = None
    simulated_users: int | None = None
    kind: Literal["badge"] = field(default="badge", init=False)


@dataclass(frozen=True)
class Snapshot(Event):
    state: dict[str, Any]
    kind: Literal["snapshot"] = field(default="snapshot", init=False)


def event_from_dict(data: dict[str, Any]) -> Event:
    """Validate the shared wire schema before recording or replaying a frame."""
    import math
    from dataclasses import fields

    classes = (
        Push,
        Tick,
        Token,
        Mode,
        Tamper,
        Badge,
        Snapshot,
        Connection,
        Guess,
        Control,
        Immune,
        Round,
        Layout,
    )
    registry = {cls.__dataclass_fields__["kind"].default: cls for cls in classes}
    cls = registry.get(data.get("kind"))
    if cls is None:
        raise ValueError("Unknown event kind")
    allowed = {f.name for f in fields(cls) if f.init}
    if set(data) - allowed - {"kind"}:
        raise ValueError("Unknown event fields")
    try:
        event = cls(**{key: value for key, value in data.items() if key != "kind"})
    except TypeError as exc:
        raise ValueError("Incomplete event") from exc
    if isinstance(event, Token):
        if not isinstance(event.i, int) or event.i < 0 or not isinstance(event.text, str):
            raise ValueError("Invalid token")
        if set(event.readout) != {"scores", "top", "margin"}:
            raise ValueError("Invalid readout")
    if isinstance(event, Layout) and (
        len(event.points) > 30
        or any(
            not isinstance(key, str)
            or len(point) != 2
            or any(not math.isfinite(v) or abs(v) > 1.000001 for v in point)
            for key, point in event.points.items()
        )
        or not set(event.alias).issubset(event.points)
    ):
        raise ValueError("Invalid layout")
    if isinstance(event, Token) and event.sky is not None:
        sky = event.sky
        if set(sky) != {"z", "pulse", "residual", "median", "drive", "clamp", "calibrated"}:
            raise ValueError("Invalid sky fields")
        values = [
            *sky["z"].values(),
            *sky["pulse"].values(),
            sky["residual"],
            sky["median"],
            sky["drive"],
            sky["clamp"],
        ]
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("Invalid sky measurement")
    if isinstance(event, Tick):
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in event.shares.values()):
            raise ValueError("Invalid shares")
        if abs(sum(event.shares.values()) - 1) > 1e-6:
            raise ValueError("Shares must sum to one")
    if isinstance(event, Badge):
        import re

        if not re.fullmatch(r"LIVE|REPLAY|SIMULATED ×\d+", event.label):
            raise ValueError("Invalid source badge")
    return event


@dataclass(frozen=True)
class Connection(Event):
    service: str
    state: str
    kind: Literal["connection"] = field(default="connection", init=False)


@dataclass(frozen=True)
class Guess(Event):
    user: str
    word: str
    t: float
    source: str
    user_id: str | None = None
    kind: Literal["guess"] = field(default="guess", init=False)


@dataclass(frozen=True)
class Control(Event):
    enabled: bool
    t: float
    source: str
    user: str = "broadcaster"
    user_id: str | None = None
    kind: Literal["control"] = field(default="control", init=False)


@dataclass(frozen=True)
class Immune(Event):
    enabled: bool
    kind: Literal["immune"] = field(default="immune", init=False)


@dataclass(frozen=True)
class Round(Event):
    mode: str
    phase: str
    answer: int
    message: str
    kind: Literal["round"] = field(default="round", init=False)


@dataclass(frozen=True)
class Layout(Event):
    points: dict[str, list[float]]
    alias: dict[str, str] = field(default_factory=dict)
    kind: Literal["layout"] = field(default="layout", init=False)
