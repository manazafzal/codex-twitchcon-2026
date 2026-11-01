import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np

from thoughtquake.engine.events import Badge, Push


def load_script(path: Path | None = None) -> dict[str, Any]:
    text = path.read_text() if path else files(__package__).joinpath("demo_script.json").read_text()
    return json.loads(text)


class Crowd:
    def __init__(
        self,
        script: dict[str, Any] | None = None,
        *,
        users: int | None = None,
        twitch_connected: bool = False,
        explicit_sim: bool = False,
    ) -> None:
        self.script = script or load_script()
        self.users = self.script["users"] if users is None else users
        self.interval = float(self.script["interval"])
        self.enabled = not twitch_connected or explicit_sim
        if self.users < 1 or self.interval <= 0 or not self.script["waves"]:
            raise ValueError("Invalid simulated crowd")
        for wave in self.script["waves"]:
            if wave["duration"] <= 0 or any(w < 0 for w in wave["weights"].values()):
                raise ValueError("Invalid crowd wave")
            if sum(wave["weights"].values()) <= 0:
                raise ValueError("Crowd wave has no factions")
        self.rng = np.random.default_rng(self.script["seed"])

    @property
    def badge(self) -> Badge:
        return Badge(f"SIMULATED ×{self.users}")

    def push_at(self, elapsed: float, timestamp: float) -> Push:
        offset = elapsed % sum(w["duration"] for w in self.script["waves"])
        wave = self.script["waves"][-1]
        for candidate in self.script["waves"]:
            wave = candidate
            if offset < wave["duration"]:
                break
            offset -= wave["duration"]
        names = list(wave["weights"])
        weights = np.array(list(wave["weights"].values()), dtype=float)
        faction = str(self.rng.choice(names, p=weights / weights.sum()))
        user = f"sim_{int(self.rng.integers(self.users)) + 1:03d}"
        return Push(user, faction, timestamp, "SIMULATED")

    async def stream(self, clock: Callable[[], float] = time.monotonic) -> AsyncIterator[Push]:
        if not self.enabled:
            return
        start = clock()
        while True:
            now = clock()
            yield self.push_at(now - start, now)
            await asyncio.sleep(self.interval)
