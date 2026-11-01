import asyncio
import copy
import json
import math
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

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
    Snapshot,
    Tamper,
    Tick,
    Token,
    event_from_dict,
)
from nous.engine.generate import Generator
from nous.engine.mixer import NEUTRAL, FakeClock
from nous.engine.rounds import FixedInjection
from nous.game.telepathy import Phase, Telepathy


class Player:
    def __init__(self, path: Path) -> None:
        self.rows: list[dict[str, Any]] = []
        previous = 0.0
        for line in path.read_text().splitlines():
            row = json.loads(line)
            timestamp = row.get("t", -1)
            if (
                not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)
                or timestamp < previous
            ):
                raise ValueError("Recording timestamps must be finite and chronological")
            if row.get("kind") not in {"meta", "frame", "push", "mode"}:
                raise ValueError("Unknown recording kind")
            if row["kind"] != "meta":
                event_from_dict(row["event"])
            previous = timestamp
            self.rows.append(row)
        if not self.rows or self.rows[0]["kind"] != "meta":
            raise ValueError("Recording must begin with metadata")
        self.metadata = self.rows[0]
        if any(row["kind"] == "meta" for row in self.rows[1:]):
            raise ValueError("Duplicate recording metadata")

    def replay_badge(self) -> Badge:
        for row in self.rows[1:]:
            original = row.get("event", {})
            if original.get("kind") == "badge":
                simulated = original.get("simulated_users")
                if original["label"].startswith("SIMULATED ×"):
                    simulated = int(original["label"].split("×")[1])
                return Badge("REPLAY", original.get("quality"), simulated)
        return Badge(
            "REPLAY", "TINY MODEL / CI" if self.metadata["model_slug"] in {"mock", "tiny"} else None
        )

    def frame_events(self) -> Iterator[tuple[float, Event]]:
        yield 0, self.replay_badge()
        for row in self.rows[1:]:
            event = event_from_dict(row["event"])
            if isinstance(event, Badge):
                continue
            if isinstance(event, Snapshot):
                event.state["badge"] = self.replay_badge().to_dict()
            yield row["t"], event

    async def frames(self, *, speed: float = 1) -> AsyncIterator[Event]:
        if speed <= 0 or not math.isfinite(speed):
            raise ValueError("Replay speed must be positive")
        previous = 0.0
        for timestamp, event in self.frame_events():
            await asyncio.sleep((timestamp - previous) / speed)
            previous = timestamp
            yield event

    def engine_events(self, engine: Generator, clock: FakeClock) -> Iterator[tuple[float, Event]]:
        """Recorded timing drives fresh model calls; recorded token text is never reused."""
        if any(
            row.get("event", {}).get("kind") == "round" and row["event"].get("phase") == "catalog"
            for row in self.rows
        ):
            raise ValueError("Topic catalog changes need --frames replay with the recorded catalog")
        if self.metadata["library_hash"] != engine.library.hash:
            raise ValueError("Replay library hash mismatch")
        if engine.mixer.schedule_mode != self.metadata["config"]["schedule_mode"]:
            raise ValueError("Replay schedule mismatch")
        yield 0, self.replay_badge()
        iterator: Iterator[Event] | None = None
        original_mixer = engine.mixer
        frozen = None
        attack_rng = None
        game = Telepathy(engine.library.concepts, clock=clock, seed=self.metadata["seed"])
        current_mode = "war"
        modern = self.metadata["config"].get("round_version", 0) >= 4
        for row in self.rows[1:]:
            clock.advance(row["t"] - clock())
            event = event_from_dict(row["event"])
            if isinstance(event, Push):
                push = replace(event, t=event.t - self.metadata.get("clock_origin", 0))
                engine.push(push)
                yield row["t"], push
            elif isinstance(event, Mode):
                if (
                    modern
                    and event.phase in {"armed", "guessing", "reveal", "idle"}
                    and iterator is not None
                ):
                    unrecorded = sum(isinstance(pending, Token) for pending in iterator)
                    if unrecorded:
                        raise ValueError("Round ended before all regenerated tokens were recorded")
                    iterator = None
                current_mode = event.mode
                if modern and event.mode == "telepathy":
                    if event.phase == "armed":
                        active = {
                            f
                            for f, share in original_mixer.tick().shares.items()
                            if f != NEUTRAL and share > 0
                        }
                        game.arm(active, secret=event.injection)
                    elif event.phase == "generating":
                        game.start()
                    elif event.phase == "guessing" and game.phase == Phase.GENERATING:
                        game.finish_generation(engine.last_scores)
                    elif event.phase == "reveal":
                        game.tick()
                    elif event.phase == "idle":
                        game.cancel()
                    if game.phase in {Phase.GUESSING, Phase.REVEAL}:
                        event = replace(
                            event,
                            scoreboard=game.scoreboard,
                            candidates=game.candidates,
                            probe_top=game.probe_top if game.phase == Phase.REVEAL else None,
                            winner=game.winner if game.phase == Phase.REVEAL else None,
                            reveal=game.secret if game.phase == Phase.REVEAL else None,
                        )
                if event.phase == "generating":
                    if event.mode == "attack":
                        if event.panel == "off":
                            engine.mixer = original_mixer
                            frozen = copy.deepcopy(original_mixer)
                            frozen.clock = FakeClock(frozen.last_time)
                            attack_rng = copy.deepcopy(engine.rng.bit_generator.state)
                        if frozen is None:
                            raise ValueError("Attack ON must follow OFF")
                        engine.mixer = (
                            FixedInjection(
                                copy.deepcopy(frozen), event.injection, beta=event.beta or 2
                            )
                            if event.injection
                            else copy.deepcopy(frozen)
                        )
                        engine.rng.bit_generator.state = copy.deepcopy(attack_rng)
                    elif event.mode == "telepathy" and event.injection:
                        engine.mixer = FixedInjection(
                            original_mixer, event.injection, beta=event.beta or 2
                        )
                    else:
                        engine.mixer = original_mixer
                    engine.secret = event.injection if event.mode == "telepathy" else None
                    engine.answer_index = event.answer
                    engine.immune = event.immune
                    iterator = engine.events(
                        max_tokens=self.metadata["config"].get("max_tokens", 32)
                    )
                yield row["t"], event
            elif isinstance(event, Tick):
                yield row["t"], engine.mixer.tick()
            elif isinstance(event, Token):
                if iterator is None:
                    raise ValueError("Token precedes answer mode")
                for generated in iterator:
                    if isinstance(generated, Token):
                        yield row["t"], generated
                        break
                else:
                    raise ValueError("Recorded token count exceeds regenerated answer")
            elif isinstance(event, Guess):
                event = replace(event, t=event.t - self.metadata.get("clock_origin", 0))
                game.guess(event.user, event.word, user_id=event.user_id, at=event.t)
                yield row["t"], event
            elif isinstance(event, Control):
                if current_mode == "war":
                    engine.immune = event.enabled
                    engine.monitor.reset()
                yield row["t"], event
            elif isinstance(event, Immune):
                engine.immune = event.enabled
                yield row["t"], event
            elif isinstance(event, Round):
                if modern and event.mode == "telepathy" and event.phase == "reveal":
                    event = replace(
                        event,
                        message=f"Telepathy reveal: {game.secret}. First correct: {game.winner or 'no winner'}.",
                    )
                yield row["t"], event
            elif isinstance(event, (Layout, Connection)):
                yield row["t"], event
            elif isinstance(event, Tamper):
                if not engine.immune:
                    continue
                if iterator is None:
                    raise ValueError("Alarm precedes answer")
                for regenerated in iterator:
                    if isinstance(regenerated, Tamper):
                        yield row["t"], regenerated
                        break
                    if isinstance(regenerated, Token):
                        raise TypeError("Alarm is missing from regenerated answer")

    async def engine(
        self, engine: Generator, clock: FakeClock, *, speed: float = 1
    ) -> AsyncIterator[Event]:
        if speed <= 0 or not math.isfinite(speed):
            raise ValueError("Replay speed must be positive")
        # Advancing this iterator can run torch; keep every call on one worker.
        from concurrent.futures import ThreadPoolExecutor

        iterator = self.engine_events(engine, clock)
        sentinel = object()
        previous = 0.0
        with ThreadPoolExecutor(max_workers=1) as worker:
            loop = asyncio.get_running_loop()
            while True:
                item = await loop.run_in_executor(worker, next, iterator, sentinel)
                if item is sentinel:
                    break
                timestamp, event = item
                await asyncio.sleep((timestamp - previous) / speed)
                previous = timestamp
                yield event
