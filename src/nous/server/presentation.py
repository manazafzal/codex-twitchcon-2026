import hashlib
import hmac
import math
import secrets
from copy import deepcopy
from dataclasses import replace

from nous.engine.events import (
    Event,
    Layout,
    Mode,
    Snapshot,
    Tamper,
    Tick,
    Token,
    event_from_dict,
)


class Presentation:
    """Remove secret identifiers before either WebSocket broadcast or snapshot reduction."""

    def __init__(self, concepts: list | None = None) -> None:
        from nous.server.secrecy import BlindProjection

        self.strict = BlindProjection(concepts) if concepts is not None else None
        self.blind = False
        self.secret = secrets.token_bytes(32)
        self.points = {}
        self.alias = {}
        self.round_id = None

    def opaque(self, key: str) -> str:
        if key in self.alias:
            return key
        return hmac.new(self.secret, f"{self.round_id}:{key}".encode(), hashlib.sha256).hexdigest()[
            :16
        ]

    def mask_ids(self) -> None:
        self.alias = {self.opaque(key): key for key in self.points}

    def layout(self) -> Layout:
        if self.strict is not None:
            return self.strict.layout()
        if not self.alias:
            return Layout(self.points)
        if self.blind:
            names = sorted(self.alias)
            return Layout(
                {
                    key: [
                        math.cos(i * 2.39996) * math.sqrt((i + 1) / len(names)),
                        math.sin(i * 2.39996) * math.sqrt((i + 1) / len(names)),
                    ]
                    for i, key in enumerate(names)
                }
            )
        return Layout({key: self.points[value] for key, value in self.alias.items()}, self.alias)

    def finish_token(self) -> Token | None:
        return self.strict.finish_token() if self.strict else None

    def event(self, event: Event) -> Event:
        if self.strict is not None:
            result = self.strict.event(event)
            self.blind, self.points = self.strict.blind, self.strict.points
            return result
        if isinstance(event, Layout):
            self.points = event.points
            if self.blind and not self.alias:
                self.mask_ids()
            return self.layout()
        if isinstance(event, Snapshot):
            data = deepcopy(event.state)
            if data.get("layout"):
                self.points = data["layout"]["points"]
            data["mode"] = self.event(event_from_dict(data["mode"])).to_dict()
            if self.points:
                data["layout"] = self.layout().to_dict()
            if self.blind:
                data["tick"] = self.event(event_from_dict(data["tick"])).to_dict()
                data["tokens"] = [
                    self.event(event_from_dict(t)).to_dict() for t in data.get("tokens", [])
                ]
                data["tamper"] = self.event(event_from_dict(data["tamper"])).to_dict()
                data["readouts"] = [
                    dict(zip("ABC", sorted(scores.values(), reverse=True)[:3], strict=False))
                    for scores in data.get("readouts", [])
                ]
            return Snapshot(data)
        if isinstance(event, Mode):
            self.blind = event.mode == "telepathy" and event.phase != "reveal"
            if self.blind and (not self.alias or self.round_id != event.round_id):
                self.round_id = event.round_id
                self.mask_ids()
            elif event.mode != "telepathy":
                self.alias = {}
            if self.blind:
                return replace(
                    event,
                    injection=None,
                    candidates=tuple("ABC"[: len(event.candidates)]),
                    reveal=None,
                    winner=None,
                    probe_top=None,
                )
        if self.blind and isinstance(event, Tick):
            return replace(
                event,
                shares={
                    key if key == "Neutral" else self.opaque(key): value
                    for key, value in event.shares.items()
                },
                top_pushers=[],
            )
        if self.blind and isinstance(event, Token):
            ranked = sorted(
                event.readout["scores"], key=lambda f: (-event.readout["scores"][f], f)
            )[:3]
            scores = {
                name: event.readout["scores"][f] for name, f in zip("ABC", ranked, strict=False)
            }
            top = next(
                (name for name, f in zip("ABC", ranked, strict=False) if f == event.readout["top"]),
                None,
            )
            sky = deepcopy(event.sky)
            if sky:
                for field in ("z", "pulse"):
                    sky[field] = {self.opaque(key): value for key, value in sky[field].items()}
            return replace(
                event,
                sky=sky,
                applied=None,
                color=None,
                readout={"scores": scores, "top": top, "margin": event.readout["margin"]},
            )
        if self.blind and isinstance(event, Tamper):
            return replace(event, concepts=("hidden concept",) if event.concepts else ())
        return event
