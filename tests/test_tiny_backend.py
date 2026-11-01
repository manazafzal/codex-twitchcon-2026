import importlib.util

import numpy as np
import pytest

from nous.model.backend import DefendSpec

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("torch") is None or importlib.util.find_spec("transformers") is None,
    reason="Optional model extra is not installed; no weights are downloaded",
)


@pytest.fixture
def backend():
    from nous.model.tiny_backend import TinyBackend

    return TinyBackend(seed=7)


def test_injection_changes_logits_and_readout(backend):
    vector = np.ones(backend.hidden_size)
    plain = backend.prefill("tea")
    injected = backend.prefill("tea")
    logits_a, h_a, _ = backend.step(plain, 97)
    logits_b, h_b, _ = backend.step(injected, 97, vector)
    assert not np.allclose(logits_a, logits_b)
    assert not np.allclose(h_a, h_b)
    assert logits_a.shape == (256,)
    assert h_a.shape == (32,)


def test_prefill_injection_changes_cache_and_next_token(backend):
    vector = np.arange(backend.hidden_size, dtype=float) / 32
    plain = backend.prefill("hello", vector, inject_prefill=False)
    changed = backend.prefill("hello", vector, inject_prefill=True)
    assert plain.position == changed.position == 5
    assert not np.allclose(plain.logits, changed.logits)

    # A later layer's cached keys must retain the injected prefill.
    def keys(cache):
        if hasattr(cache, "layers"):
            return cache.layers[-1].keys.detach().numpy()
        return cache[-1][0].detach().numpy()

    assert not np.allclose(keys(plain.cache), keys(changed.cache))
    next_a, _, a = backend.step(plain, 97)
    next_b, _, b = backend.step(changed, 97)
    assert a.position == b.position == 6
    assert not np.allclose(next_a, next_b)


def test_defender_reduces_projection_and_hooks_are_removed(backend):
    direction = np.ones((1, 32)) / np.sqrt(32)
    spec = DefendSpec(direction, np.array([0.1]), ("test",))
    state = backend.prefill("tea")
    _, _, defended = backend.step(state, 97, np.ones(32), spec)
    assert defended.defence_pre[0] > 0.1
    assert defended.defence_post[0] <= 0.10001
    assert all(not block._forward_hooks for block in backend.model.model.layers)
    assert backend.embed_texts(["tea", "ab"], backend.readout_layer).shape == (2, 32)


def test_prefill_clamp_and_no_injection_leak(backend):
    vector = np.ones(32)
    spec = DefendSpec(vector[None, :], np.array([0.1]), ("test",))
    reference = backend.prefill("tea")
    defended = backend.prefill("tea", vector, spec, inject_prefill=True)
    assert defended.defence_pre[0] > 0.1
    assert defended.defence_post[0] <= 0.10001
    clean_again = backend.prefill("tea")
    np.testing.assert_array_equal(reference.logits, clean_again.logits)
    assert backend.tokenizer.encode("hello") == list(b"hello")


def test_position_zero_is_excluded_and_zero_vector_is_exact(backend):
    zero = np.zeros(backend.hidden_size)
    plain = backend.prefill("hello")
    injected = backend.prefill("hello", zero, inject_prefill=True)
    np.testing.assert_array_equal(plain.logits, injected.logits)
    vector = np.arange(backend.hidden_size, dtype=float) / 32
    changed = backend.prefill("hello", vector, inject_prefill=True)

    def keys(cache):
        return (
            cache.layers[-1].keys.detach().numpy()
            if hasattr(cache, "layers")
            else cache[-1][0].detach().numpy()
        )

    np.testing.assert_array_equal(keys(plain.cache)[:, :, 0], keys(changed.cache)[:, :, 0])
    assert not np.allclose(keys(plain.cache)[:, :, 1:], keys(changed.cache)[:, :, 1:])
    assert backend.token_hidden("abc", backend.injection_layer).shape == (2, 32)
    with pytest.raises(ValueError, match="position zero"):
        backend.token_hidden("a", backend.injection_layer)


def test_large_first_position_cannot_enter_embeddings(backend):
    def sink(module, args, output):
        h = output[0] if isinstance(output, tuple) else output
        h = h.clone()
        h[:, 0] = 1e6
        return (h, *output[1:]) if isinstance(output, tuple) else h

    handle = backend.model.model.layers[backend.injection_layer].register_forward_hook(sink)
    try:
        rows = backend.token_hidden("abc", backend.injection_layer)
        assert rows.shape == (2, 32) and np.max(np.abs(rows)) < 100
    finally:
        handle.remove()
