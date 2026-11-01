from thoughtquake.model.hf_backend import HFBackend


class ByteTokenizer:
    eos_token_id = None

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, tokens: list[int], skip_special_tokens: bool = True) -> str:
        return bytes(tokens).decode("utf-8", errors="replace")


class TinyBackend(HFBackend):
    """Random local Qwen2 fixture, sharing production hooks without fetching weights."""

    def __init__(self, seed: int = 0) -> None:
        try:
            import torch
            from transformers import Qwen2Config, Qwen2ForCausalLM
        except ImportError as exc:
            raise ImportError("TinyBackend requires thoughtquake[model]") from exc
        config = Qwen2Config(
            vocab_size=256,
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=3,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=512,
            eos_token_id=None,
        )
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            model = Qwen2ForCausalLM(config).eval()
        self.tokenizer = ByteTokenizer()
        self._configure(model)
