from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

Vector = npt.NDArray[np.floating[Any]]


@dataclass(frozen=True)
class DefendSpec:
    directions: Vector
    thresholds: Vector
    concepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class State:
    logits: Vector
    readout_hidden: Vector
    cache: Any = None
    position: int = 0
    defender_hidden: Vector | None = None
    defence_pre: Vector | None = None
    defence_post: Vector | None = None
    layer_hidden: dict[int, Vector] = field(default_factory=dict)


class ModelBackend(Protocol):
    num_layers: int
    hidden_size: int
    injection_layer: int
    readout_layer: int
    eos_token_id: int | None

    def prefill(
        self,
        prompt: str,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
        *,
        inject_prefill: bool = True,
    ) -> State: ...

    def step(
        self,
        state: State,
        token: int,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
    ) -> tuple[Vector, Vector, State]: ...

    def sample(
        self, logits: Vector, temperature: float, top_p: float, rng: np.random.Generator
    ) -> int: ...

    def decode(self, tokens: list[int]) -> str: ...

    def embed_texts(self, texts: list[str], layer: int) -> Vector: ...


def sample(logits: Vector, temperature: float, top_p: float, rng: np.random.Generator) -> int:
    if temperature < 0 or not 0 < top_p <= 1:
        raise ValueError("Invalid sampling parameters")
    if temperature == 0:
        return int(np.argmax(logits))
    values = np.asarray(logits, dtype=np.float64) / temperature
    probs = np.exp(values - values[int(np.argmax(values))])
    probs /= probs.sum()
    order = np.argsort(-probs, kind="stable")
    keep = np.cumsum(probs[order]) - probs[order] < top_p
    chosen = order[keep]
    p = probs[chosen]
    return int(rng.choice(chosen, p=p / p.sum()))


class TokenProbe(Protocol):
    def token_hidden(self, text: str, layer: int) -> Vector: ...
