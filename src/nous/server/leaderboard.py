"""The engine owner is the sole writer; replacement makes a crash leave the prior file intact."""

import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any


class Leaderboard:
    def __init__(self, path: Path | None = None, *, stream_id: str | None = None) -> None:
        self.path = path
        self.stream_id = stream_id or uuid.uuid4().hex
        self.all_time: dict[str, dict[str, Any]] = {}
        self.factions: dict[str, dict[str, Any]] = {}
        self.stream: dict[str, dict[str, Any]] = {}
        self.stream_factions: dict[str, dict[str, Any]] = {}
        if path and path.exists():
            data = json.loads(path.read_text())
            if data.get("version") not in {1, 2}:
                raise ValueError("Unknown leaderboard version")
            self.all_time = self.validate(data["viewers"])
            self.factions = self.validate(data["factions"])
            if data["version"] == 2:
                saved_id = data["stream_id"]
                if not isinstance(saved_id, str) or not saved_id:
                    raise ValueError("Invalid stream id")
                if stream_id is None or stream_id == saved_id:
                    self.stream_id = saved_id
                    self.stream = self.validate(data["stream"])
                    self.stream_factions = self.validate(data["stream_factions"])

    @staticmethod
    def validate(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        for key, row in rows.items():
            if (
                set(row) != {"id", "name", "points"}
                or key != row["id"]
                or not isinstance(row["name"], str)
                or not math.isfinite(row["points"])
                or row["points"] < 0
            ):
                raise ValueError("Invalid leaderboard entry")
        return rows

    def add(self, viewer: str, name: str, points: float, faction: str | None = None) -> None:
        if not math.isfinite(points) or points < 0:
            raise ValueError("Invalid points")
        for board, key, label in ((self.stream, viewer, name), (self.all_time, viewer, name)):
            row = board.setdefault(key, {"id": key, "name": label, "points": 0.0})
            row["name"], row["points"] = label, row["points"] + points
        if faction:
            for board in (self.factions, self.stream_factions):
                row = board.setdefault(faction, {"id": faction, "name": faction, "points": 0.0})
                row["points"] += points

    @staticmethod
    def top(board: dict[str, dict[str, Any]], count: int = 5) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in sorted(
                board.values(), key=lambda row: (-row["points"], row["name"].casefold(), row["id"])
            )[:count]
        ]

    def snapshot(self, *, blind: bool = False) -> dict[str, Any]:
        return {
            "stream": self.top(self.stream),
            "all_time": self.top(self.all_time),
            "factions": {
                "stream": [] if blind else self.top(self.stream_factions),
                "all_time": [] if blind else self.top(self.factions),
            },
        }

    def rank(self, viewer: str) -> tuple[int | None, float]:
        for i, row in enumerate(self.top(self.stream, len(self.stream))):
            if row["id"] == viewer:
                return i + 1, float(row["points"])
        return None, 0.0

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".json")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(
                    {
                        "version": 2,
                        "viewers": self.all_time,
                        "factions": self.factions,
                        "stream_id": self.stream_id,
                        "stream": self.stream,
                        "stream_factions": self.stream_factions,
                    },
                    handle,
                    allow_nan=False,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
