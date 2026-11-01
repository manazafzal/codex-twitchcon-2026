import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self, TextIO

from thoughtquake.engine.events import Event, Mode, Push, event_from_dict


class Recorder:
    def __init__(
        self, path: Path, metadata: dict[str, Any], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        required = {"config", "seed", "model_slug", "library_hash", "app_version"}
        if not required <= metadata.keys():
            raise ValueError("Incomplete recording metadata")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file: TextIO = path.open("w", encoding="utf-8")
        self.clock, self.start = clock, clock()
        self.holding = False
        self.ready = False
        self.held: list[dict[str, Any]] = []
        metadata = json.loads(json.dumps(metadata))
        script = metadata["config"].get("sim_script")
        if script:
            import hashlib

            metadata["config"]["sim_script"] = {
                "sha256": hashlib.sha256(json.dumps(script, sort_keys=True).encode()).hexdigest()
            }
        self._write({"t": 0.0, "kind": "meta", "clock_origin": self.start, **metadata})

    def _write(self, row: dict[str, Any]) -> None:
        self.file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        self.file.flush()

    def record(self, event: Event, *, timestamp: float | None = None) -> None:
        event_from_dict(event.to_dict())
        kind = "push" if isinstance(event, Push) else "mode" if isinstance(event, Mode) else "frame"
        row = {
            "t": (self.clock() if timestamp is None else timestamp) - self.start,
            "kind": kind,
            "event": event.to_dict(),
        }
        if isinstance(event, Mode) and event.mode == "telepathy":
            if event.phase in {"armed", "generating", "guessing"}:
                self.holding = True
            elif event.phase == "reveal":
                self.ready = True
            elif event.phase == "idle" and not self.ready:
                self.held.clear()
                self.holding = False
        if self.holding:
            self.held.append(row)
        else:
            self._write(row)

    def release(self) -> None:
        if self.ready:
            for row in self.held:
                self._write(row)
            self.held.clear()
            self.holding = self.ready = False

    def close(self) -> None:
        self.release()
        self.held.clear()
        self.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
