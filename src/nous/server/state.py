from collections import deque
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from nous.concepts.library import Concept
from nous.engine.events import (
    Badge,
    Connection,
    Control,
    Event,
    Immune,
    Layout,
    Mode,
    Push,
    Round,
    Snapshot,
    Tamper,
    Tick,
    Token,
)


class ViewState:
    """One reducer supplies WebSocket snapshots and the public state endpoint."""

    def __init__(self, concepts: list[Concept] | None = None) -> None:
        self.catalog = [asdict(c) for c in concepts or []]
        self.data: dict[str, Any] = {
            "concepts": [asdict(c) for c in concepts or []],
            "badge": Badge("SIMULATED ×0", "TINY MODEL / CI").to_dict(),
            "mode": Mode("war", False, "Waiting for the Subject…", 0).to_dict(),
            "tick": Tick({"Neutral": 1.0}, 0, [], 0).to_dict(),
            "tamper": Tamper((), 0).to_dict(),
            "tokens": [],
            "history": [],
            "panels": {"off": [], "on": []},
            "pushes": [],
            "readouts": [],
            "connections": {},
            "immune": Immune(False).to_dict(),
            "immune_requested": False,
            "layout": None,
            "leaderboard": None,
            "mvp": None,
        }

    def apply(self, event: Event) -> None:
        row = event.to_dict()
        if isinstance(event, Snapshot):
            self.data = deepcopy(event.state)
        elif isinstance(event, (Badge, Tick, Tamper, Immune, Layout)):
            self.data[event.kind] = row
        elif isinstance(event, Control):
            self.data["immune_requested"] = event.enabled
        elif isinstance(event, Connection):
            self.data["connections"][event.service] = event.state
        elif isinstance(event, Push):
            self.data["pushes"] = [*self.data["pushes"], row][-5:]
        elif isinstance(event, Round) and event.phase == "mvp":
            import json

            card = json.loads(event.message)
            self.data["leaderboard"], self.data["mvp"] = card["board"], card["mvp"]
        elif isinstance(event, Mode):
            previous = self.data["mode"]
            if event.mode == "telepathy" and event.phase != "reveal":
                self.data["concepts"] = []
                self.data["leaderboard"] = None
                self.data["mvp"] = None
                self.data["history"] = []
                self.data["panels"] = {"off": [], "on": []}
                self.data["pushes"] = []
            else:
                self.data["concepts"] = self.catalog
            new_answer = (event.answer, event.panel, event.mode) != (
                previous["answer"],
                previous["panel"],
                previous["mode"],
            )
            if new_answer and event.phase in {"armed", "generating"}:
                if self.data["tokens"] and not (
                    event.mode == "telepathy" and event.phase != "reveal"
                ):
                    self.data["history"] = [
                        *self.data["history"],
                        {"mode": previous, "tokens": self.data["tokens"]},
                    ][-3:]
                self.data["tokens"] = []
                if event.mode != "attack" or event.panel == "off":
                    self.data["panels"] = {"off": [], "on": []}
            self.data["mode"] = row
            self.data["immune"] = Immune(event.immune).to_dict()
            if event.mode == "telepathy" and new_answer:
                self.data["readouts"] = []
        elif isinstance(event, Token):
            self.data["tokens"] = [*self.data["tokens"], row][-256:]
            if self.data["mode"]["mode"] == "attack":
                panel = self.data["mode"]["panel"]
                self.data["panels"][panel] = [*self.data["panels"].get(panel, []), row][-256:]
            readouts = deque(self.data["readouts"], maxlen=60)
            readouts.append(event.readout["scores"])
            self.data["readouts"] = list(readouts)

    def snapshot(self) -> Snapshot:
        return Snapshot(deepcopy(self.data))
