"""Private token traces, never sent through the public event stream."""

from dataclasses import replace
from typing import Any

import numpy as np

from nous.concepts.library import ConceptLibrary
from nous.engine.events import Push, Tamper
from nous.engine.generate import Generator
from nous.engine.immune import unit
from nous.engine.mixer import FakeClock, ForcedMixer
from nous.model.backend import State, Vector
from nous.model.hf_backend import HFBackend


class ResearchMixer(ForcedMixer):
    """Larger doses are confined to this adapter; production validation stays intact."""

    def __init__(self, concept: str, alpha: float, norm: float, clock: FakeClock) -> None:
        super().__init__(concept, alpha=0, median_norm=norm, clock=clock)
        if not 0 <= alpha <= 1.5:
            raise ValueError("Research alpha out of registered range")
        self.research_alpha = alpha
        self.target = concept

    def vector(self, vectors: dict[str, Vector]) -> Vector:
        direction = unit(vectors[self.target])
        return direction * self.research_alpha * self.median_norm * min(1, self.tick().beta)


class CaptureBackend:
    def __init__(self, backend: HFBackend) -> None:
        self.backend = backend
        self.states: list[State] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    def prefill(self, *args: Any, **kwargs: Any) -> State:
        self.states.clear()
        return self.backend.prefill(*args, **kwargs)

    def step(self, *args: Any, **kwargs: Any) -> tuple[Vector, Vector, State]:
        logits, hidden, state = self.backend.step(*args, **kwargs)
        # KV objects are mutable and huge; retain only measured vectors.
        self.states.append(replace(state, cache=None, logits=np.empty(0)))
        return logits, hidden, state


def uninjected(
    capture: CaptureBackend,
    prompt: str,
    seed: int,
    tokens: int = 32,
) -> tuple[str, dict[int, Vector]]:
    state = capture.prefill(prompt)
    rng = np.random.default_rng(seed)
    ids = []
    for _ in range(tokens):
        token = capture.sample(state.logits, 0.8, 0.95, rng)
        if token == capture.eos_token_id:
            break
        ids.append(token)
        _, _, state = capture.step(state, token)
    if not ids:
        raise ValueError("Empty generation; cell remains unrun")
    layers = {
        i: np.stack([s.layer_hidden[i] for s in capture.states])
        for i in sorted(capture.backend.probe_layers)
    }
    return capture.decode(ids), layers


def answer(
    capture: CaptureBackend,
    library: ConceptLibrary,
    concept: str,
    prompt: str,
    seed: int,
    alpha: float,
    immune: bool,
) -> tuple[str, list[State]]:
    clock = FakeClock()
    mixer = ResearchMixer(concept, alpha, library.median_residual_norm, clock)
    engine = Generator(
        capture, library, mixer, seed=seed, immune=immune, clock=clock, simulated_users=60
    )
    for user in range(60):
        engine.push(Push(f"sim_{user:03}", concept, 0, "SIMULATED"))
    frames = list(engine.events(prompt=prompt, max_tokens=32))
    if not immune and any(isinstance(frame, Tamper) for frame in frames):
        raise AssertionError("Immune OFF emitted a tamper report")
    if not capture.states or not engine.last_text.strip():
        raise ValueError("Empty generation; incomplete cell remains unrun")
    return engine.last_text, capture.states.copy()
