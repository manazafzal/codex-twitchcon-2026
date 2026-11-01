import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np

from mindwars.concepts.library import ConceptLibrary
from mindwars.engine.events import Badge, Event, Mode, Push, Tamper, Token
from mindwars.engine.immune import ImmuneMonitor
from mindwars.engine.mixer import NEUTRAL, Mixer
from mindwars.engine.readout import Readout
from mindwars.model.backend import ModelBackend

PROMPTS = (
    "Explain how to make tea.",
    "Suggest a morning routine.",
    "Describe how to pack a bag.",
    "Explain how to repair a bicycle tyre.",
    "Plan a simple school day.",
    "Explain how to fold a shirt.",
    "Suggest an easy lunch.",
    "Explain how to tidy a desk.",
    "Describe how to wash dishes.",
    "Plan a relaxing evening.",
    "Explain how to organise a cupboard.",
    "Suggest a short exercise routine.",
    "Explain how to write a thank-you note.",
    "Describe how to choose comfortable shoes.",
    "Plan a weekly shopping list.",
    "Explain how to clean a window.",
    "Describe how to mend a button.",
    "Suggest a simple breakfast.",
    "Explain how to set a table.",
    "Describe how to organise a calendar.",
    "Suggest a rainy-day activity.",
    "Explain how to wrap a gift.",
    "Describe how to prepare for a meeting.",
    "Explain how to take useful notes.",
    "Suggest a bedtime routine.",
    "Describe how to sort laundry.",
    "Explain how to keep a room cool.",
    "Plan an afternoon walk.",
    "Describe how to prepare a picnic.",
    "Explain how to sharpen a pencil.",
    "Suggest ways to save water at home.",
    "Explain how to store leftovers.",
    "Describe how to make a paper envelope.",
    "Explain how to charge a phone safely.",
    "Suggest a simple stretching routine.",
    "Explain how to compare two prices.",
    "Describe how to organise photographs.",
    "Explain how to care for a houseplant.",
    "Suggest a plan for finishing homework.",
    "Explain how to check a bicycle brake.",
)


def readout_allowed(path: Path | None, schedule_mode: str) -> bool:
    if path is None:
        return False
    try:
        data = json.loads(path.read_text())
        return (
            data["source"] == "realmodel"
            and data["schedule_modes"][schedule_mode]["window_agreement"] >= 0.75
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


class Generator:
    def __init__(
        self,
        backend: ModelBackend,
        library: ConceptLibrary,
        mixer: Mixer,
        *,
        seed: int = 0,
        immune: bool = False,
        window: int = 12,
        margin_threshold: float = 0.1,
        colour_source: Literal["applied", "readout"] = "applied",
        eval_path: Path | None = None,
        inject_prefill: bool = True,
        source: Literal["LIVE", "REPLAY", "SIMULATED"] = "SIMULATED",
        simulated_users: int = 0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if colour_source not in {"applied", "readout"}:
            raise ValueError("Invalid colour source")
        if colour_source == "readout" and not readout_allowed(eval_path, mixer.schedule_mode):
            raise ValueError("Mind-Reader colours require real-model window agreement >= 0.75")
        if source not in {"LIVE", "REPLAY", "SIMULATED"} or simulated_users < 0:
            raise ValueError("Invalid source badge")
        if backend.hidden_size != library.V.shape[1]:
            raise ValueError("Backend and library dimensions differ")
        self.backend, self.library, self.mixer = backend, library, mixer
        self.rng = np.random.default_rng(seed)
        self.immune, self.inject_prefill = immune, inject_prefill
        self.readout = Readout(library, window=window, margin_threshold=margin_threshold)
        self.colour_source, self.clock = colour_source, clock
        self.badge = f"SIMULATED ×{simulated_users}" if source == "SIMULATED" else source
        self.monitor = ImmuneMonitor()
        self.history: deque[list[Token]] = deque(maxlen=3)
        self.pending: deque[Push] = deque()

    def push(self, event: Push) -> float:
        if event.faction not in self.library.ids:
            raise ValueError("Unknown faction")
        weight = self.mixer.push(event)
        self.pending.append(event)
        return weight

    def events(
        self,
        *,
        answers: int = 1,
        max_tokens: int = 32,
        temperature: float = 0.8,
        top_p: float = 0.95,
    ) -> Iterator[Event]:
        if answers < 1 or max_tokens < 1:
            raise ValueError("Answers and token budget must be positive")
        yield Badge(self.badge)
        vectors = dict(zip(self.library.ids, self.library.V, strict=True))
        defend = self.library.defender() if self.immune else None
        for answer in range(answers):
            self.readout.reset()
            self.monitor.reset()
            prompt = PROMPTS[answer % len(PROMPTS)]
            yield Mode("war", self.immune, prompt, answer)
            while self.pending:
                yield self.pending.popleft()
            yield self.mixer.tick()
            last_tick = self.clock()
            applied = self.mixer.select(0, self.rng)
            vector = self.mixer.vector(vectors)
            state = self.backend.prefill(prompt, vector, defend, inject_prefill=self.inject_prefill)
            tokens: list[int] = []
            emitted = ""
            frames = []
            for i in range(max_tokens):
                while self.pending:
                    yield self.pending.popleft()
                if self.clock() - last_tick >= 0.5:
                    yield self.mixer.tick()
                    last_tick = self.clock()
                if i:
                    applied = self.mixer.select(i, self.rng)
                    vector = self.mixer.vector(vectors)
                token = self.backend.sample(state.logits, temperature, top_p, self.rng)
                if token == self.backend.eos_token_id:
                    break
                tokens.append(token)
                _, hidden, state = self.backend.step(state, token, vector, defend)
                active = [
                    f for f, share in self.mixer.tick().shares.items() if f != NEUTRAL and share > 0
                ]
                reading = self.readout.observe(hidden, active)
                decoded = self.backend.decode(tokens).rstrip("\ufffd")
                text = decoded[len(emitted) :]
                emitted = decoded
                color = applied if self.colour_source == "applied" else reading.color
                frame = Token(
                    i,
                    text,
                    applied,
                    {k: v for k, v in asdict(reading).items() if k != "color"},
                    color,
                )
                frames.append(frame)
                yield frame
                pre = state.defence_pre
                post = state.defence_post
                if pre is None:
                    pre = post = np.zeros(len(self.library.ids))
                decision = self.monitor.observe(
                    self.library.ids,
                    pre,
                    post,
                    self.library.thresholds if defend else np.full(len(self.library.ids), np.inf),
                    readout_top=reading.top,
                    margin=reading.margin,
                    margin_threshold=self.readout.margin_threshold,
                    pushed=set(active),
                )
                yield Tamper(decision.concepts, decision.neutralised)
            self.history.append(frames)

    async def stream(
        self, *, answers: int = 1, max_tokens: int = 32, pause: float = 2.0
    ) -> AsyncIterator[Event]:
        """Run model calls on one worker while the IO loop remains responsive."""
        iterator = self.events(answers=answers, max_tokens=max_tokens)
        loop = asyncio.get_running_loop()
        sentinel = object()
        seen_answer = False
        with ThreadPoolExecutor(max_workers=1) as worker:
            while True:
                event = await loop.run_in_executor(worker, next, iterator, sentinel)
                if event is sentinel:
                    break
                if isinstance(event, Mode):
                    if seen_answer:
                        await asyncio.sleep(max(2.0, pause))
                    seen_answer = True
                yield event
