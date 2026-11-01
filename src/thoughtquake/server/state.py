from collections import deque
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from thoughtquake.concepts.library import Concept
from thoughtquake.engine.events import Badge, Event, Mode, Push, Snapshot, Tamper, Tick, Token


class ViewState:
    """One reducer supplies WebSocket snapshots and the public state endpoint."""

    def __init__(self, concepts: list[Concept] | None = None) -> None:
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
        }

    def apply(self, event: Event) -> None:
        row = event.to_dict()
        if isinstance(event, Snapshot):
            self.data = deepcopy(event.state)
        elif isinstance(event, (Badge, Tick, Tamper)):
            self.data[event.kind] = row
        elif isinstance(event, Push):
            self.data["pushes"] = [*self.data["pushes"], row][-5:]
        elif isinstance(event, Mode):
            previous = self.data["mode"]
            new_answer = (event.answer, event.panel, event.mode) != (
                previous["answer"],
                previous["panel"],
                previous["mode"],
            )
            if new_answer and event.phase == "generating":
                if self.data["tokens"]:
                    self.data["history"] = [
                        *self.data["history"],
                        {"mode": previous, "tokens": self.data["tokens"]},
                    ][-3:]
                self.data["tokens"] = []
                if event.mode != "attack" or event.panel == "off":
                    self.data["panels"] = {"off": [], "on": []}
            self.data["mode"] = row
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
