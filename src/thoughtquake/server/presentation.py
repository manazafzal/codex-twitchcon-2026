from copy import deepcopy
from dataclasses import replace

from thoughtquake.engine.events import Event, Mode, Snapshot, Tamper, Token, event_from_dict


class Presentation:
    """Remove secret identifiers before either WebSocket broadcast or snapshot reduction."""

    def __init__(self) -> None:
        self.blind = False

    def event(self, event: Event) -> Event:
        if isinstance(event, Snapshot):
            data = deepcopy(event.state)
            data["mode"] = self.event(event_from_dict(data["mode"])).to_dict()
            if self.blind:
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
            if self.blind:
                return replace(
                    event,
                    injection=None,
                    candidates=tuple("ABC"[: len(event.candidates)]),
                    reveal=None,
                    winner=None,
                    probe_top=None,
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
            return replace(
                event,
                applied=None,
                color=None,
                readout={"scores": scores, "top": top, "margin": event.readout["margin"]},
            )
        if self.blind and isinstance(event, Tamper):
            return replace(event, concepts=("hidden concept",) if event.concepts else ())
        return event
