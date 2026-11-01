import hashlib

import numpy as np

from thoughtquake.engine.immune import clamp
from thoughtquake.model.backend import DefendSpec, State, Vector, sample


class MockBackend:
    """A deterministic plumbing fixture; its output is not evidence of model quality."""

    num_layers = 12
    hidden_size = 32
    injection_layer = 7
    readout_layer = 11
    eos_token_id = None
    sample = staticmethod(sample)
    words = (" A", " calm", " day", " brings", " fresh", " ideas", ".", " ocean", " space", " jazz")

    def _hidden(self, text: str, layer: int) -> Vector:
        seed = int.from_bytes(hashlib.sha256(f"{layer}:{text}".encode()).digest()[:8])
        return np.random.default_rng(seed).normal(0, 0.05, self.hidden_size)

    def _run(
        self, text: str, position: int, inject: Vector | None, defend: DefendSpec | None
    ) -> State:
        hidden = self._hidden(text, self.injection_layer)
        if inject is not None:
            hidden += inject
        before = hidden.copy()
        pre = post = None
        if defend is not None:
            hidden, pre, post = clamp(hidden, defend)
        logits = np.full(len(self.words), -8.0)
        dominant = int(np.argmax(hidden[:3]))
        token = 7 + dominant if np.linalg.norm(hidden) > 1 else position % 7
        logits[token] = 8
        return State(logits, hidden, text, position, before, pre, post)

    def prefill(
        self,
        prompt: str,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
        *,
        inject_prefill: bool = False,
    ) -> State:
        return self._run(prompt, 0, inject if inject_prefill else None, defend)

    def step(
        self,
        state: State,
        token: int,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
    ) -> tuple[Vector, Vector, State]:
        result = self._run(self.decode([token]), state.position + 1, inject, defend)
        return result.logits, result.readout_hidden, result

    def decode(self, tokens: list[int]) -> str:
        return "".join(self.words[token] for token in tokens)

    def embed_texts(self, texts: list[str], layer: int) -> Vector:
        return np.stack([self._hidden(text, layer) for text in texts])
