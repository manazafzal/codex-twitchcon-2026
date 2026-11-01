"""Word-boundary output projection; no raw blind-round payload reaches public state."""

import hashlib
import hmac
import math
import re
import secrets
from copy import deepcopy
from dataclasses import replace
from typing import Any

from nous.concepts.library import Concept, concept_pattern
from nous.engine.events import (
    Control,
    Event,
    Guess,
    Layout,
    Mode,
    Push,
    Round,
    Snapshot,
    Tamper,
    Tick,
    Token,
    event_from_dict,
)


class BlindProjection:
    def __init__(self, concepts: list[Concept]) -> None:
        self.concepts = concepts
        self.key = secrets.token_bytes(32)
        self.round_key: tuple[int | None, int] | None = None
        self.patterns = [concept_pattern(c, stems=True) for c in concepts]
        self.ids = {c.id: f"voc{i:03}" for i, c in enumerate(concepts)}
        self.blind = False
        self.round_id: int | None = None
        self.points: dict[str, list[float]] = {}
        self.tail = ""
        self.last: Token | None = None
        self.offset = 0

    def clean(self, text: str) -> str:
        for pattern in self.patterns:
            text = pattern.sub("\u2592", text)
        return text

    def words(self, text: str) -> str:
        self.tail += text
        boundaries = list(re.finditer(r"\S+\s+", self.tail))
        if boundaries:
            end = boundaries[-1].end()
            self.tail = self.clean(self.tail[:end]) + self.tail[end:]
        complete = list(re.finditer(r"\S+\s+", self.tail))
        if len(complete) < 2:
            return ""
        cut = complete[-2].end()
        result, self.tail = self.tail[:cut], self.tail[cut:]
        return self.clean(result)

    def finish_token(self) -> Token | None:
        if not self.blind or not self.tail or self.last is None:
            return None
        text = self.clean(self.tail)
        self.tail = ""
        return Token(self.last.i, text, None, {"scores": {}, "top": None, "margin": 0.0}, None)

    def opaque(self, key: str) -> str:
        return self.ids.get(key, key if re.fullmatch(r"voc\d{3}", key) else "?")

    def layout(self) -> Layout:
        names = sorted(self.points, key=self.opaque)
        if self.blind:
            # The round rotation changes the anonymous constellation, independent of real PCA axes.
            count = max(1, len(names))
            return Layout(
                {
                    self.opaque(name): [
                        math.cos((i + self.offset) * 2.399963) * math.sqrt((i + 0.5) / count),
                        math.sin((i + self.offset) * 2.399963) * math.sqrt((i + 0.5) / count),
                    ]
                    for i, name in enumerate(names)
                },
                None,
            )
        return Layout(
            {self.opaque(name): point for name, point in self.points.items()},
            {self.opaque(name): name for name in self.points},
        )

    def snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(state)
        if data.get("mode"):
            data["mode"] = self.event(event_from_dict(data["mode"])).to_dict()
        if not self.blind:
            return data
        data["concepts"] = []
        data["leaderboard"] = None
        data["mvp"] = None
        data["history"] = []
        data["panels"] = {"off": [], "on": []}
        data["pushes"] = [
            self.event(event_from_dict(row)).to_dict() for row in data.get("pushes", [])
        ]
        data["tokens"] = []
        for original in state.get("tokens", []):
            row = deepcopy(original)
            row.update(text=self.clean(row["text"]), applied=None, color=None)
            row["readout"]["scores"] = {
                self.opaque(key): value for key, value in row["readout"]["scores"].items()
            }
            if row["readout"]["top"]:
                row["readout"]["top"] = self.opaque(row["readout"]["top"])
            if row.get("sky"):
                for field in ("z", "pulse"):
                    row["sky"][field] = {
                        self.opaque(key): value for key, value in row["sky"][field].items()
                    }
            data["tokens"].append(row)
        data["readouts"] = [
            {self.opaque(key): value for key, value in scores.items()}
            for scores in data.get("readouts", [])
            if all(key.startswith("voc") for key in scores)
        ]
        if data.get("tick"):
            data["tick"] = self.event(event_from_dict(data["tick"])).to_dict()
        if data.get("tamper"):
            data["tamper"] = self.event(event_from_dict(data["tamper"])).to_dict()
        data["layout"] = self.layout().to_dict() if self.points else None
        return data

    def event(self, event: Event) -> Event:
        if isinstance(event, Layout):
            self.points = event.points
            return self.layout() if self.blind else event
        if isinstance(event, Mode):
            blind = event.mode == "telepathy" and event.phase != "reveal"
            if blind and (not self.blind or self.round_key != (event.round_id, event.answer)):
                self.round_id = event.round_id
                self.round_key = (event.round_id, event.answer)
                self.offset = (self.round_id or event.answer) + 1
                self.tail = ""
                ordered = sorted(
                    self.concepts,
                    key=lambda c: hmac.new(
                        self.key, f"{self.round_key}:{c.id}".encode(), hashlib.sha256
                    ).digest(),
                )
                self.ids = {c.id: f"voc{i:03}" for i, c in enumerate(ordered)}
            self.blind = blind
            if blind:
                return replace(
                    event,
                    prompt=self.clean(event.prompt),
                    injection=None,
                    candidates=(),
                    reveal=None,
                    winner=None,
                    probe_top=None,
                    probe_accuracy=None,
                    scoreboard=tuple(
                        (self.clean(name), points) for name, points in event.scoreboard
                    ),
                )
        if isinstance(event, Snapshot):
            return Snapshot(self.snapshot(event.state))
        if not self.blind:
            return event
        if isinstance(event, Token):
            self.last = event
            sky = deepcopy(event.sky)
            if sky:
                for key in ("z", "pulse"):
                    sky[key] = {self.opaque(name): value for name, value in sky[key].items()}
            scores = {self.opaque(key): value for key, value in event.readout["scores"].items()}
            top = self.opaque(event.readout["top"]) if event.readout["top"] else None
            return replace(
                event,
                text=self.words(event.text),
                applied=None,
                color=None,
                sky=sky,
                readout={"scores": scores, "top": top, "margin": event.readout["margin"]},
            )
        if isinstance(event, Push):
            return replace(event, faction="?", user=self.clean(event.user))
        if isinstance(event, Tick):
            quiet = event.shares.get("Neutral", 0)
            return replace(event, shares={"Neutral": quiet, "?": 1 - quiet}, top_pushers=[])
        if isinstance(event, Guess):
            return replace(event, word="\u2592", user=self.clean(event.user))
        if isinstance(event, Control):
            return replace(event, user=self.clean(event.user))
        if isinstance(event, Tamper):
            return replace(event, concepts=("hidden",) if event.concepts else ())
        if isinstance(event, Round):
            return replace(event, message=self.clean(event.message))
        return event
