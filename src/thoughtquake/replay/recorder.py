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
        self._write({"t": 0.0, "kind": "meta", "clock_origin": self.start, **metadata})

    def _write(self, row: dict[str, Any]) -> None:
        self.file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        self.file.flush()

    def record(self, event: Event, *, timestamp: float | None = None) -> None:
        event_from_dict(event.to_dict())
        kind = "push" if isinstance(event, Push) else "mode" if isinstance(event, Mode) else "frame"
        self._write(
            {
                "t": (self.clock() if timestamp is None else timestamp) - self.start,
                "kind": kind,
                "event": event.to_dict(),
            }
        )

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
