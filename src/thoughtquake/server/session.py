import asyncio
import copy
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import numpy as np

from thoughtquake.concepts.library import ConceptLibrary, load_concepts
from thoughtquake.engine.events import Badge, Event, Mode, Push, Token
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.model.backend import ModelBackend
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.replay.recorder import Recorder
from thoughtquake.sim.crowd import Crowd


def mock_library() -> ConceptLibrary:
    concepts = load_concepts()[:3]
    vectors = np.eye(32)[:3]
    return ConceptLibrary(
        concepts, vectors, vectors.copy(), np.zeros(32), np.full(3, 0.1), {"model": "mock"}
    )


class Session:
    def __init__(
        self,
        *,
        backend: ModelBackend | None = None,
        library: ConceptLibrary | None = None,
        crowd: Crowd | None = None,
        seed: int = 2026,
        recorder: Recorder | None = None,
    ) -> None:
        self.library = library or mock_library()
        self.crowd = crowd or Crowd()
        self.clock = FakeClock()
        self.started = time.monotonic()
        self.engine = Generator(
            backend or MockBackend(),
            self.library,
            Mixer(clock=self.clock),
            seed=seed,
            simulated_users=self.crowd.users,
            clock=self.clock,
        )
        self.seed, self.recorder = seed, recorder
        self.mode = "war"
        self.pending: asyncio.Queue[Push] = asyncio.Queue(maxsize=1024)

    def switch_mode(self, mode: str) -> None:
        self.mode = mode

    def metadata(self) -> dict[str, Any]:
        return {
            "config": {
                "schedule_mode": self.engine.mixer.schedule_mode,
                "max_tokens": 32,
                "sim_script": self.crowd.script,
            },
            "seed": self.seed,
            "model_slug": "mock" if isinstance(self.engine.backend, MockBackend) else "tiny",
            "backend_seed": getattr(self.engine.backend, "seed", 0),
            "library_hash": self.library.hash,
            "app_version": "0.1.0",
        }

    def drain(self) -> list[Push]:
        accepted = []
        while not self.pending.empty():
            push = self.pending.get_nowait()
            event = replace(push, t=self.engine.mixer.clock())
            self.engine.push(event)
            self.engine.pending.pop()
            accepted.append(event)
        return accepted

    async def _crowd(self) -> None:
        async for push in self.crowd.stream():
            await self.pending.put(push)

    async def _answer(self, mode: str, panel: str = "main") -> AsyncIterator[Event]:
        stream = self.engine.stream(max_tokens=32)
        try:
            async for event in self._advance(stream):
                yield self._present(event, mode, panel)
        finally:
            await stream.aclose()

    def _present(self, event: Event, mode: str, panel: str) -> Event:
        if isinstance(event, Mode):
            return replace(event, mode=mode, panel=panel)
        return event

    async def _advance(
        self, stream: AsyncIterator[Event], *, drain: bool = True
    ) -> AsyncIterator[Event]:
        while True:
            self.clock.advance(max(0, time.monotonic() - self.started - self.clock()))
            if drain:
                for push in self.drain():
                    yield push
            event = await anext(stream, None)
            if event is None:
                break
            if isinstance(event, Badge):
                continue
            yield event
            if isinstance(event, Token):
                await asyncio.sleep(0.08)

    async def _events(self) -> AsyncIterator[Event]:
        yield replace(
            self.crowd.badge,
            quality="TINY MODEL / CI" if self.library.config.get("model") == "mock" else None,
        )
        crowd_task = asyncio.create_task(self._crowd())
        try:
            while True:
                selected = self.mode
                self.clock.advance(max(0, time.monotonic() - self.started - self.clock()))
                for push in self.drain():
                    yield push
                if selected == "attack":
                    original = self.engine.mixer
                    frozen = copy.deepcopy(original)
                    frozen.clock = FakeClock(frozen._last)
                    rng_state = copy.deepcopy(self.engine.rng.bit_generator.state)
                    answer = self.engine.answer_index
                    for panel in ("off", "on"):
                        self.engine.mixer = copy.deepcopy(frozen)
                        self.engine.rng.bit_generator.state = copy.deepcopy(rng_state)
                        self.engine.answer_index = answer
                        self.engine.immune = panel == "on"
                        # The comparison is isolated from new pushes until both passes finish.
                        async for event in self._advance(
                            self.engine.stream(max_tokens=32), drain=False
                        ):
                            if isinstance(event, Badge):
                                continue
                            if isinstance(event, Mode):
                                event = replace(event, mode="attack", panel=panel)
                            yield event
                        await asyncio.sleep(2)
                    self.engine.mixer = original
                    self.engine.immune = False
                elif selected == "telepathy":
                    async for event in self._answer("telepathy"):
                        yield event
                    last = self.engine.answer_index - 1
                    secret = self.engine.mixer._selected
                    from thoughtquake.engine.generate import PROMPTS

                    for remaining in range(30, -1, -1):
                        self.clock.advance(max(0, time.monotonic() - self.started - self.clock()))
                        yield Mode(
                            "telepathy",
                            False,
                            PROMPTS[last % len(PROMPTS)],
                            last,
                            phase="guessing",
                            remaining=remaining,
                        )
                        if self.mode != selected:
                            break
                        await asyncio.sleep(1)
                    if self.mode == selected:
                        yield Mode(
                            "telepathy",
                            False,
                            PROMPTS[last % len(PROMPTS)],
                            last,
                            phase="reveal",
                            reveal=secret or "Neutral",
                        )
                else:
                    self.engine.immune = False
                    async for event in self._answer("war"):
                        yield event
                await asyncio.sleep(2)
        finally:
            crowd_task.cancel()
            try:
                await crowd_task
            except asyncio.CancelledError:
                pass

    async def events(self) -> AsyncIterator[Event]:
        try:
            async for event in self._events():
                if self.recorder:
                    self.recorder.record(event)
                yield event
        finally:
            if self.recorder:
                self.recorder.close()
