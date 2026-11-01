import asyncio
import copy
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import numpy as np

from nous.concepts.library import ConceptLibrary, load_concepts, match_concept
from nous.engine.commands import Command, Rank, SetMode, StartRound
from nous.engine.events import (
    Badge,
    Connection,
    Control,
    Event,
    Guess,
    Immune,
    Layout,
    Mode,
    Push,
    Round,
    Tamper,
    Token,
)
from nous.engine.generate import PROMPTS, Generator
from nous.engine.mixer import NEUTRAL, FakeClock, Mixer
from nous.engine.rounds import FixedInjection
from nous.game.telepathy import Phase, Telepathy
from nous.model.backend import ModelBackend
from nous.model.mock_backend import MockBackend
from nous.replay.recorder import Recorder
from nous.server.leaderboard import Leaderboard
from nous.server.scoring import Scoring
from nous.sim.crowd import Crowd


def mock_library(*, all_concepts: bool = True) -> ConceptLibrary:
    concepts = load_concepts() if all_concepts else load_concepts()[:3]
    vectors = np.eye(32)[: len(concepts)]
    neutral = MockBackend().embed_texts(list(MockBackend.words), MockBackend.readout_layer)
    neutral /= np.maximum(np.linalg.norm(neutral, axis=1, keepdims=True), 1e-8)
    return ConceptLibrary(
        concepts,
        vectors,
        vectors.copy(),
        np.zeros(32),
        np.full(len(concepts), 0.1),
        {"model": "mock"},
        neutral[:, : len(concepts)].mean(axis=0),
        np.maximum(neutral[:, : len(concepts)].std(axis=0), 1e-6),
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
        source: Literal["LIVE", "REPLAY", "SIMULATED"] = "SIMULATED",
        clock: FakeClock | None = None,
        colour_source: Literal["applied", "readout"] = "applied",
        eval_path: Path | None = None,
        schedule_mode: str = "answer",
        leaderboard: Leaderboard | None = None,
    ) -> None:
        self.source, self.library, self.crowd = source, library or mock_library(), crowd or Crowd()
        self.clock, self.realtime = clock or FakeClock(), clock is None
        self.started = time.monotonic()
        self.engine = Generator(
            backend or MockBackend(),
            self.library,
            Mixer(clock=self.clock, schedule_mode=schedule_mode),
            seed=seed,
            simulated_users=self.crowd.users,
            source=source,
            clock=self.clock,
            colour_source=colour_source,
            eval_path=eval_path,
        )
        self.seed, self.recorder, self.mode = seed, recorder, "war"
        self.immune_enabled = False
        self.current_mode = "war"
        self.pending: asyncio.Queue[Command] = asyncio.Queue(maxsize=1024)
        self.owner: asyncio.Task | None = None
        self.scoring = Scoring(leaderboard, clock=self.now)
        self.controller: tuple[str, str] | None = None
        self.answer_running = False
        self.pending_points: deque[tuple[Push, float]] = deque()
        self.round_hits: dict[str, float] = {}
        self.telepathy = Telepathy(self.library.concepts, clock=self.clock, seed=seed)
        self.round_answer = 0
        self._revealed = False
        self.probe_accuracy: float | None = None
        if eval_path:
            try:
                evidence = json.loads(eval_path.read_text())
                metric = evidence["telepathy"]
                accuracy = float(metric["accuracy"])
                if evidence["source"] == "realmodel" and metric["n"] > 0 and 0 <= accuracy <= 1:
                    self.probe_accuracy = accuracy
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def now(self) -> float:
        return time.monotonic() - self.started if self.realtime else self.clock()

    def sync_time(self) -> None:
        self.clock.advance(max(0, self.now() - self.clock()))

    def switch_mode(self, mode: str) -> None:
        if mode not in {"war", "attack", "telepathy"}:
            raise ValueError("Unknown mode")
        self.pending.put_nowait(SetMode(mode))

    def start_round(self) -> None:
        self.pending.put_nowait(StartRound())

    def set_immune(self, enabled: bool) -> None:
        self.pending.put_nowait(Control(enabled, self.now(), "LOCAL"))

    async def submit(self, command: Command) -> None:
        await self.pending.put(command)

    def metadata(self) -> dict[str, Any]:
        return {
            "config": {
                "schedule_mode": self.engine.mixer.schedule_mode,
                "max_tokens": 32,
                "sim_script": self.crowd.script,
                "all_concepts": len(self.library.concepts) > 3,
                "source": self.source,
                "colour_source": self.engine.colour_source,
                "window": self.engine.readout.window.maxlen,
                "round_version": 4,
            },
            "seed": self.seed,
            "model_slug": (
                "mock"
                if isinstance(self.engine.backend, MockBackend)
                else "tiny"
                if type(self.engine.backend).__name__ == "TinyBackend"
                else self.library.config["model"]
            ),
            "backend_seed": getattr(self.engine.backend, "seed", 0),
            "library_hash": self.library.hash,
            "app_version": "0.1.0",
        }

    def telepathy_mode(self) -> Mode:
        game = self.telepathy
        reveal = game.phase == Phase.REVEAL
        return Mode(
            "telepathy",
            False,
            PROMPTS[self.round_answer % len(PROMPTS)],
            self.round_answer,
            phase=game.phase.value,
            remaining=game.remaining,
            scoreboard=game.scoreboard,
            candidates=game.candidates,
            reveal=game.secret if reveal else None,
            round_id=game.round_id,
            winner=game.winner if reveal else None,
            probe_top=game.probe_top if reveal else None,
            probe_accuracy=self.probe_accuracy,
            colour_source=self.engine.colour_source,
            injection=game.secret,
            beta=2,
        )

    def reveal_events(self) -> list[Event]:
        if self._revealed or self.telepathy.phase != Phase.REVEAL:
            return []
        self._revealed = True
        game = self.telepathy
        mvp = self.scoring.finish({})
        message = f"Telepathy reveal: {game.secret}. First correct: {game.winner or 'no winner'}."
        events: list[Event] = [
            self.telepathy_mode(),
            Round("telepathy", "reveal", self.round_answer, message),
        ]
        if mvp:
            events.append(
                Round(
                    "telepathy",
                    "mvp",
                    self.round_answer,
                    json.dumps(
                        {
                            "mvp": {"id": mvp.viewer, "name": mvp.name, "points": mvp.points},
                            "board": self.scoring.board.snapshot(),
                        },
                        separators=(",", ":"),
                    ),
                )
            )
        return events

    def drain(self) -> list[Event]:
        accepted: list[Event] = []
        guessing_batch = self.telepathy.phase == Phase.GUESSING and not self._revealed
        while not self.pending.empty():
            item = self.pending.get_nowait()
            if isinstance(item, StartRound):
                if self.telepathy.phase == Phase.IDLE:
                    self.mode = "telepathy"
                    accepted.append(
                        Round(
                            self.current_mode,
                            "notice",
                            self.engine.answer_index,
                            "New round starting! Get ready to guess.",
                        )
                    )
                else:
                    accepted.append(
                        Round(
                            self.current_mode,
                            "notice",
                            self.engine.answer_index,
                            "A round is already running. Try !guess <word>.",
                        )
                    )
                continue
            if isinstance(item, SetMode):
                self.mode = item.mode
                continue
            if isinstance(item, Rank):
                rank, points = self.scoring.board.rank(item.user_id)
                message = f"Viewer rank: {rank or 'unranked'}; {points:.2f} points."
                accepted.append(Round(self.current_mode, "rank", self.engine.answer_index, message))
                continue
            if isinstance(item, Push):
                event = replace(item, t=self.engine.mixer.clock())
                weight = self.engine.push(event, emit=False)
                if self.answer_running and self.engine.mixer.schedule_mode == "answer":
                    if weight > 0:
                        self.pending_points.append((event, weight))
                else:
                    self.credit_push(event, weight)
                accepted.append(event)
            elif isinstance(item, Guess):
                accepted.append(item)
                if (
                    guessing_batch
                    and self.telepathy.started_at is not None
                    and self.telepathy.deadline is not None
                    and self.telepathy.started_at <= item.t < self.telepathy.deadline
                ):
                    points = self.scoring.guess(
                        item.user_id or item.user,
                        item.user,
                        correct=match_concept(item.word, self.library.concepts)
                        == self.telepathy.secret,
                        at=item.t,
                    )
                    if points:
                        self.telepathy.guess(item.user, item.word, user_id=item.user_id, at=item.t)
                else:
                    self.telepathy.tick(item.t)
            else:
                if item.enabled and item.source == "LIVE" and item.user_id:
                    self.controller = (item.user_id, item.user)
                elif not item.enabled or item.source == "LOCAL":
                    self.controller = None
                self.immune_enabled = item.enabled
                accepted.append(replace(item, t=self.clock()))
                # A showcase comparison and a secret challenge keep their prescribed defence.
                if self.current_mode == "war" and self.telepathy.phase == Phase.IDLE:
                    self.engine.immune = item.enabled
                    self.engine.monitor.reset()
                accepted.append(Immune(self.engine.immune))
        accepted.extend(self.reveal_events())
        return accepted

    def credit_push(self, event: Push, weight: float) -> None:
        self.scoring.push(
            event.user_id or event.user,
            event.user,
            event.faction,
            weight,
            at=event.t,
        )

    def begin_round(self) -> None:
        self.answer_running = False
        self.controller = None
        self.round_hits = {}
        self.scoring.begin(self.engine.answer_index)
        while self.pending_points:
            event, weight = self.pending_points.popleft()
            self.credit_push(event, weight)

    async def _crowd(self) -> None:
        async for push in self.crowd.stream():
            await self.pending.put(push)

    async def _advance(
        self, stream: AsyncIterator[Event], *, drain: bool = True
    ) -> AsyncIterator[Event]:
        try:
            while True:
                self.sync_time()
                if drain:
                    for event in self.drain():
                        yield event
                event = await anext(stream, None)
                if event is None:
                    break
                if isinstance(event, Badge):
                    continue
                yield event
                if isinstance(event, Token):
                    await asyncio.sleep(0.08)
        finally:
            await stream.aclose()

    async def _answer(
        self,
        mode: str,
        panel: str = "main",
        *,
        drain: bool = True,
        finalise: bool = True,
    ) -> AsyncIterator[Event]:
        applied: set[str] = set()
        self.answer_running = True
        try:
            async with aclosing(
                self._advance(self.engine.stream(max_tokens=32), drain=drain)
            ) as stream:
                async for event in stream:
                    if isinstance(event, Mode):
                        if mode == "telepathy":
                            event = self.telepathy_mode()
                        else:
                            plan = (
                                self.engine.mixer
                                if isinstance(self.engine.mixer, FixedInjection)
                                else None
                            )
                            event = replace(
                                event,
                                mode=mode,
                                panel=panel,
                                injection=plan.faction if plan else None,
                                beta=plan.strength if plan else None,
                            )
                    if isinstance(event, Token) and event.applied:
                        applied.add(event.applied)
                    if isinstance(event, Tamper) and self.controller:
                        self.scoring.catch(
                            *self.controller,
                            true_concept=self.engine.mixer.selected,
                            attributed=event.concepts,
                            immune=self.engine.immune,
                        )
                    yield event
        finally:
            self.answer_running = False
        mentioned = self.library.mentioned_in(self.engine.last_text) - self.engine.last_exempt
        for key in applied & mentioned:
            self.round_hits[key] = 1.0
        mvp = self.scoring.finish(self.round_hits) if mode != "telepathy" and finalise else None
        if mvp:
            message = json.dumps(
                {
                    "mvp": {"id": mvp.viewer, "name": mvp.name, "points": mvp.points},
                    "board": self.scoring.board.snapshot(),
                },
                separators=(",", ":"),
            )
            yield Round(mode, "mvp", self.engine.answer_index - 1, message)

    async def _attack(self) -> AsyncIterator[Event]:
        original = self.engine.mixer
        frozen = copy.deepcopy(original)
        frozen.clock = FakeClock(frozen.last_time)
        active = {
            f: share for f, share in frozen.tick().shares.items() if f != NEUTRAL and share > 0
        }
        faction = max(active, key=active.get) if active else self.library.ids[0]
        rng_state = copy.deepcopy(self.engine.rng.bit_generator.state)
        answer = self.engine.answer_index
        yield Round(
            "attack",
            "start",
            answer,
            "Attack round: the same thought injection, IMMUNE OFF then ON.",
        )
        try:
            for panel in ("off", "on"):
                self.engine.mixer = FixedInjection(copy.deepcopy(frozen), faction)
                self.engine.rng.bit_generator.state = copy.deepcopy(rng_state)
                self.engine.answer_index, self.engine.immune = answer, panel == "on"
                yield Immune(self.engine.immune)
                async with aclosing(
                    self._answer("attack", panel, drain=False, finalise=panel == "on")
                ) as stream:
                    async for event in stream:
                        yield event
                await asyncio.sleep(2)
        finally:
            self.engine.mixer, self.engine.immune = original, self.immune_enabled
        yield Round("attack", "end", answer, "Attack comparison complete.")

    async def _telepathy(self) -> AsyncIterator[Event]:
        active = {
            f for f, share in self.engine.mixer.tick().shares.items() if f != NEUTRAL and share > 0
        }
        secret = self.telepathy.arm(active)
        self.round_answer = self.engine.answer_index
        self._revealed = False
        yield Round(
            "telepathy",
            "start",
            self.round_answer,
            "Telepathy round: guess the hidden concept with !guess <word>.",
        )
        yield self.telepathy_mode()
        original = self.engine.mixer
        self.engine.mixer = FixedInjection(original, secret)
        self.engine.secret, self.engine.immune = secret, False
        yield Immune(False)
        try:
            self.telepathy.start()
            async with aclosing(self._answer("telepathy")) as stream:
                async for event in stream:
                    yield event
            self.telepathy.finish_generation(self.engine.last_scores)
            yield self.telepathy_mode()
            while self.telepathy.phase == Phase.GUESSING and self.mode == "telepathy":
                self.sync_time()
                for event in self.drain():
                    yield event
                self.telepathy.tick()
                for event in self.reveal_events():
                    yield event
                if self.telepathy.phase == Phase.GUESSING:
                    yield self.telepathy_mode()
                    await asyncio.sleep(0.1)
            if self.telepathy.phase == Phase.REVEAL:
                await asyncio.sleep(2)
                self.telepathy.reset()
            else:
                self.telepathy.cancel()
            yield self.telepathy_mode()
            yield Round("telepathy", "end", self.round_answer, "Telepathy round complete.")
        finally:
            self.engine.mixer, self.engine.secret = original, None
            self.engine.immune = self.immune_enabled
            self.telepathy.cancel()

    async def _events(self) -> AsyncIterator[Event]:
        badge = (
            self.crowd.badge
            if self.source == "SIMULATED"
            else Badge(
                self.source, simulated_users=self.crowd.users if self.crowd.enabled else None
            )
        )
        yield replace(
            badge, quality="TINY MODEL / CI" if self.library.config.get("model") == "mock" else None
        )
        yield Layout(self.engine.atlas.points)
        crowd_task = asyncio.create_task(self._crowd())
        try:
            while True:
                self.sync_time()
                self.begin_round()
                for event in self.drain():
                    yield event
                self.current_mode = self.mode
                if self.mode == "attack":
                    async with aclosing(self._attack()) as stream:
                        async for event in stream:
                            yield event
                elif self.mode == "telepathy":
                    async with aclosing(self._telepathy()) as stream:
                        async for event in stream:
                            yield event
                else:
                    self.engine.immune = self.immune_enabled
                    answer = self.engine.answer_index
                    yield Immune(self.engine.immune)
                    yield Round(
                        "war", "start", answer, "War round: type a concept word to join a faction."
                    )
                    async for event in self._answer("war"):
                        yield event
                    yield Round("war", "end", answer, "The Subject's answer is complete.")
                await asyncio.sleep(2)
        finally:
            crowd_task.cancel()
            try:
                await crowd_task
            except asyncio.CancelledError:
                pass

    async def events(self) -> AsyncIterator[Event]:
        if self.owner is not None:
            raise RuntimeError("The engine already has an owner")
        self.owner = asyncio.current_task()
        delay = 0.5
        recovering = False
        try:
            while True:
                stream = self._events()
                try:
                    async for event in stream:
                        if self.recorder:
                            self.recorder.record(event)
                        if isinstance(event, Token):
                            delay = 0.5
                            if recovering:
                                yield Connection("engine", "connected")
                                recovering = False
                        yield event
                        if self.recorder and isinstance(event, Mode) and event.phase == "reveal":
                            self.recorder.release()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - supervise arbitrary backend failures without private text
                    recovering = True
                    self.telepathy.cancel()
                    self._revealed = False
                    logging.getLogger(__name__).error("Producer failed; restarting the Subject")
                    yield Connection("engine", "error")
                    await asyncio.sleep(delay)
                    delay = min(10, delay * 2)
                finally:
                    await stream.aclose()
        finally:
            self.owner = None
            if self.recorder:
                self.recorder.close()
