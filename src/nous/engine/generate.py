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

from nous.concepts.library import ConceptLibrary
from nous.concepts.probe import lda_scores
from nous.engine.atlas import AtlasSignals
from nous.engine.events import Badge, Event, Mode, Push, Tamper, Token
from nous.engine.immune import AlarmMonitor
from nous.engine.mixer import NEUTRAL, Mixer
from nous.engine.readout import Readout
from nous.model.backend import ModelBackend, Vector

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
        margin_threshold: float | None = None,
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
        for name in ("injection_layer", "readout_layer"):
            if name in library.config and library.config[name] != getattr(backend, name):
                raise ValueError("Backend layer configuration differs from the library; rebuild it")
        self.backend, self.library, self.mixer = backend, library, mixer
        self.rng = np.random.default_rng(seed)
        self.immune, self.inject_prefill = immune, inject_prefill
        self.readout = Readout(library, window=window, margin_threshold=margin_threshold)
        self.colour_source, self.clock = colour_source, clock
        self.badge = f"SIMULATED ×{simulated_users}" if source == "SIMULATED" else source
        self.monitor = AlarmMonitor()
        if library.variant == "others" and mixer.alpha is None:
            mixer.alpha, mixer.median_norm = 0.45, library.median_residual_norm
        self.last_layer_means: dict[int, Vector] = {}
        self.last_text = ""
        self.last_prompt = ""
        self.last_alarm_tokens: list[bool] = []
        self.last_flagged: set[str] = set()
        self.last_exempt: set[str] = set()
        self.history: deque[list[Token]] = deque(maxlen=3)
        self.pending: deque[Push] = deque()
        self.atlas = AtlasSignals(library)
        self.answer_index = 0
        self.secret: str | None = None
        self.last_scores: dict[str, float] = {}

    def push(self, event: Push, *, emit: bool = True, passive: bool = False) -> float:
        if event.faction not in self.library.ids:
            raise ValueError("Unknown faction")
        weight = self.mixer.push(event, passive=True) if passive else self.mixer.push(event)
        if emit:
            self.pending.append(event)
        return weight

    def _flush(
        self,
        group: list[tuple[Token, Tamper, Vector, list[str], dict[int, Vector]]],
        frames: list[Token],
    ) -> Iterator[Event]:
        if not group:
            return
        reading = None
        if self.colour_source == "readout" or self.library.readout_v4:
            mean = np.mean([item[2] for item in group], axis=0)
            reading = self.readout.decide(
                mean,
                group[-1][3],
                self.secret,
                features=self.readout.features([item[4] for item in group]),
            )
        if self.colour_source == "readout":
            assert reading is not None
            colour = reading.color
        else:
            votes: dict[str | None, int] = {}
            for frame, _, _, _, _ in group:
                votes[frame.applied] = votes.get(frame.applied, 0) + 1
            colour = min(votes, key=lambda candidate: (-votes[candidate], candidate or ""))
        for frame, tamper, _, _, _ in group:
            readout = frame.readout
            if self.library.readout_v4 and reading is not None:
                readout = {
                    "scores": readout["scores"],
                    "top": reading.top,
                    "margin": reading.margin,
                }
            frame = Token(frame.i, frame.text, frame.applied, readout, colour, frame.sky)
            frames.append(frame)
            yield frame
            if self.immune:
                yield tamper
        group.clear()

    def events(
        self,
        *,
        answers: int = 1,
        max_tokens: int = 32,
        temperature: float = 0.8,
        top_p: float = 0.95,
        prompt: str | None = None,
    ) -> Iterator[Event]:
        if answers < 1 or max_tokens < 1:
            raise ValueError("Answers and token budget must be positive")
        quality = (
            "TINY MODEL / CI"
            if self.library.config.get("model") in {"mock", "TINY MODEL / CI"}
            else None
        )
        yield Badge(self.badge, quality)
        vectors = dict(zip(self.library.ids, self.library.V, strict=True))
        for _ in range(answers):
            answer = self.answer_index
            self.answer_index += 1
            self.readout.reset()
            self.monitor.reset()
            self.last_scores = {}
            chosen_prompt = prompt or PROMPTS[answer % len(PROMPTS)]
            self.last_prompt = chosen_prompt
            self.last_text = ""
            self.last_alarm_tokens = []
            self.last_flagged = set()
            self.last_exempt = self.library.mentioned_in(chosen_prompt)
            layer_positions: list[dict[int, Vector]] = []
            yield Mode("war", self.immune, chosen_prompt, answer, colour_source=self.colour_source)
            while self.pending:
                yield self.pending.popleft()
            yield self.mixer.tick()
            last_tick = self.clock()
            applied = self.mixer.select(0, self.rng)
            vector = self.mixer.vector(vectors)
            defend = self.library.defender() if self.immune else None
            state = self.backend.prefill(
                chosen_prompt, vector, defend, inject_prefill=self.inject_prefill
            )
            self.atlas.begin(state.readout_hidden)
            tokens: list[int] = []
            emitted = ""
            frames: list[Token] = []
            answer_hidden = []
            group: list[tuple[Token, Tamper, Vector, list[str], dict[int, Vector]]] = []
            grouped = (
                self.colour_source == "readout"
                or self.mixer.schedule_mode == "token"
                or bool(self.library.readout_v4)
            )
            width = (
                max_tokens
                if self.mixer.schedule_mode == "answer"
                else int(self.readout.window.maxlen or 12)
            )

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
                defend = self.library.defender() if self.immune else None
                _, hidden, state = self.backend.step(state, token, vector, defend)
                answer_hidden.append(hidden.copy())
                active = [
                    f for f, share in self.mixer.tick().shares.items() if f != NEUTRAL and share > 0
                ]
                layers = state.layer_hidden or {self.backend.readout_layer: hidden}
                layer_positions.append(layers)
                reading = self.readout.observe(hidden, active, self.secret, layers)
                decoded = self.backend.decode(tokens).rstrip("\ufffd")
                text, emitted = decoded[len(emitted) :], decoded
                frame = Token(
                    i,
                    text,
                    applied,
                    {k: v for k, v in asdict(reading).items() if k != "color"},
                    applied,
                    self.atlas.observe(hidden, state, reading.scores),
                )
                pre, post = state.defence_pre, state.defence_post
                if pre is None or post is None:
                    from nous.engine.immune import unit

                    pre = (
                        state.defender_hidden @ unit(self.library.V).T
                        if state.defender_hidden is not None
                        else np.zeros(len(self.library.ids))
                    )
                    post = pre.copy()
                thresholds = self.library.alarm_thresholds
                if thresholds is None:
                    thresholds = np.full(len(self.library.ids), np.inf)
                decision = self.monitor.observe(
                    self.library.ids, pre, post, thresholds, reading.scores, exempt=self.last_exempt
                )
                self.last_alarm_tokens.append(decision.token_alarm)
                named = (decision.concept,) if decision.fired and decision.concept else ()
                self.last_flagged.update(named)
                tamper = Tamper(named, decision.neutralised)
                if grouped:
                    group.append((frame, tamper, hidden, active, layers))
                    if len(group) >= width:
                        yield from self._flush(group, frames)
                else:
                    frames.append(frame)
                    yield frame
                    if self.immune:
                        yield tamper
            yield from self._flush(group, frames)
            self.last_text = emitted
            self.last_layer_means = (
                {
                    layer: np.mean([item[layer] for item in layer_positions], axis=0)
                    for layer in layer_positions[0]
                }
                if layer_positions
                else {}
            )
            if answer_hidden:
                self.last_scores = self.readout.decide(
                    np.mean(answer_hidden, axis=0), list(self.library.ids)
                ).scores
                features = self.readout.features(layer_positions)
                if features is not None and self.library.readout_v4:
                    self.last_scores = dict(
                        zip(
                            self.library.ids,
                            map(float, lda_scores(self.library.readout_v4, features)),
                            strict=True,
                        )
                    )
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
                if isinstance(event, Event):
                    yield event
