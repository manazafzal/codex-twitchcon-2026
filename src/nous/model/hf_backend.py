import os
from typing import Any

import numpy as np

from nous.config import require_model_path
from nous.model.backend import DefendSpec, State, Vector, sample


class HFBackend:
    """Hooks operate on every position in the current forward, never cached positions."""

    sample = staticmethod(sample)

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        *,
        local_path: str | None = None,
    ) -> None:
        location = str(require_model_path(local_path))
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise ImportError("Install nous[model] to use this backend") from exc
        name = model_name or os.getenv("NOUS_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
        allowed = {"Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-1.5B-Instruct"}
        if name not in allowed:
            raise ValueError("Unsupported model")
        target = device or os.getenv("NOUS_DEVICE", "cpu")
        if target == "auto":
            target = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(location, local_files_only=True)
        loader: Any = AutoModelForCausalLM
        model = loader.from_pretrained(location, local_files_only=True)
        self._configure(model.to(target).eval())

    def _configure(self, model: Any) -> None:
        if model.config.model_type != "qwen2":
            raise ValueError("Local weights must use the supported Qwen2 architecture")
        self.model = model
        self.num_layers = model.config.num_hidden_layers
        self.hidden_size = model.config.hidden_size
        self.injection_layer = 16 if self.num_layers > 22 else round(0.55 * self.num_layers)
        self.readout_layer = self.injection_layer + 4
        if self.readout_layer >= self.num_layers:
            # Tiny fixtures retain the same hook order with a shorter readout gap.
            self.injection_layer = max(0, self.num_layers - 3)
            self.readout_layer = self.num_layers - 1
        self.probe_layers = {self.injection_layer, self.readout_layer, min(22, self.num_layers - 1)}
        self.eos_token_id = self.tokenizer.eos_token_id

    def _ids(self, text: str) -> list[int]:
        return self.tokenizer.encode(text) or [self.eos_token_id or 0]

    def _forward(
        self,
        ids: list[int],
        cache: Any = None,
        position: int = 0,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
        capture_layer: int | None = None,
    ) -> tuple[State, Vector]:
        import torch

        captured: dict[str, Any] = {}
        layer_states: dict[int, Vector] = {}
        handles = []

        def hook(layer: int) -> Any:
            def apply(module: Any, args: Any, output: Any) -> Any:
                h = output[0] if isinstance(output, tuple) else output
                start = 1 if position == 0 else 0
                if layer == self.injection_layer and inject is not None and bool(np.any(inject)):
                    h = h.clone()
                    h[:, start:] += torch.as_tensor(inject, device=h.device, dtype=h.dtype)
                if layer == self.injection_layer + 1:
                    captured["defender"] = h.detach().float().cpu().numpy()[0, -1].copy()
                    if defend is not None:
                        directions = torch.as_tensor(
                            defend.directions, device=h.device, dtype=h.dtype
                        )
                        directions = torch.nn.functional.normalize(directions, dim=-1)
                        thresholds = torch.as_tensor(
                            defend.thresholds, device=h.device, dtype=h.dtype
                        )
                        captured["pre"] = (h[0, -1] @ directions.T).detach().float().cpu().numpy()
                        h = h.clone()
                        work = h[:, start:]
                        for direction, threshold in zip(directions, thresholds, strict=True):
                            work = (
                                work
                                - (work @ direction - threshold).clamp(min=0).unsqueeze(-1)
                                * direction
                            )
                        h[:, start:] = work
                        captured["post"] = (h[0, -1] @ directions.T).detach().float().cpu().numpy()
                if layer in self.probe_layers:
                    layer_states[layer] = h.detach().float().cpu().numpy()[0, -1].copy()
                if layer == self.readout_layer:
                    captured["readout"] = h.detach().float().cpu().numpy()[0, -1].copy()
                if layer == capture_layer:
                    captured["embedding"] = h.detach().float().cpu().numpy()[0, start:].copy()
                return (h, *output[1:]) if isinstance(output, tuple) else h

            return apply

        try:
            for layer, block in enumerate(self.model.model.layers):
                handles.append(block.register_forward_hook(hook(layer)))
            with torch.inference_mode():
                out = self.model(
                    input_ids=torch.tensor([ids], device=self.model.device),
                    past_key_values=cache,
                    use_cache=True,
                )
            state = State(
                out.logits[0, -1].float().cpu().numpy(),
                captured["readout"],
                out.past_key_values,
                position + len(ids),
                captured.get("defender"),
                captured.get("pre"),
                captured.get("post"),
                layer_states,
            )
            return state, captured.get("embedding", np.empty((0, self.hidden_size)))
        finally:
            for handle in handles:
                handle.remove()

    def prefill(
        self,
        prompt: str,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
        *,
        inject_prefill: bool = True,
    ) -> State:
        if hasattr(self.tokenizer, "apply_chat_template"):
            prompt = self.tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
            )
        return self._forward(
            self._ids(prompt), inject=inject if inject_prefill else None, defend=defend
        )[0]

    def step(
        self,
        state: State,
        token: int,
        inject: Vector | None = None,
        defend: DefendSpec | None = None,
    ) -> tuple[Vector, Vector, State]:
        result, _ = self._forward([token], state.cache, state.position, inject, defend)
        return result.logits, result.readout_hidden, result

    def decode(self, tokens: list[int]) -> str:
        return self.tokenizer.decode(tokens, skip_special_tokens=True)

    def embed_texts(self, texts: list[str], layer: int) -> Vector:
        if not 0 <= layer < self.num_layers:
            raise ValueError("Invalid layer")
        return np.stack([self.token_hidden(text, layer).mean(axis=0) for text in texts])

    def token_hidden(self, text: str, layer: int) -> Vector:
        result = self._forward(self._ids(text), capture_layer=layer)[1]
        if not len(result):
            raise ValueError("Text has no positions after excluding position zero")
        return result
