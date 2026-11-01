import os
from pathlib import Path

import numpy as np
import pytest

from nous.concepts.library import ConceptLibrary
from nous.engine.events import Mode, Token
from nous.engine.generate import Generator
from nous.engine.mixer import FakeClock, ForcedMixer
from nous.evaluation import evaluate
from nous.model.hf_backend import HFBackend
from nous.server.secrecy import BlindProjection

pytestmark = [
    pytest.mark.realmodel,
    pytest.mark.skipif(
        os.getenv("NOUS_REAL") != "1", reason="Local trained weights are not enabled"
    ),
]


@pytest.fixture(scope="module")
def backend():
    try:
        return HFBackend(local_path=os.getenv("NOUS_MODEL_PATH"))
    except (OSError, ImportError):
        pytest.skip("Trained weights are not available locally")


@pytest.fixture(scope="module")
def library():
    path = Path(os.getenv("NOUS_LIBRARY", "library/qwen2.5-0.5b-instruct.npz"))
    if not path.exists():
        pytest.skip("Trained library is unavailable")
    return ConceptLibrary.load(path)


@pytest.fixture(scope="module")
def report(backend, library):
    if not library.readout_v4:
        pytest.skip("Fitted v4 parameters are unavailable")
    return evaluate(backend, library, alphas=[0.45], seeds=1, prompts=3, concepts=12, held_out=1)


def test_real_alpha_zero_logits_equal_uninjected(backend):
    a = backend.prefill("Explain how to make tea.")
    b = backend.prefill(
        "Explain how to make tea.", np.zeros(backend.hidden_size), inject_prefill=True
    )
    np.testing.assert_array_equal(a.logits, b.logits)


def test_real_injected_hit_exceeds_control(report):
    on = next(row for row in report["rows"] if row["alpha"] == 0.45 and not row["immune"])
    control = next(row for row in report["rows"] if row["alpha"] == 0 and not row["immune"])
    assert control["metrics"]["keyword_hit"]["mean"] == 0
    assert on["metrics"]["keyword_hit"]["mean"] > control["metrics"]["keyword_hit"]["mean"]


def test_real_blind_readout_and_false_alarm(report):
    injected = next(row for row in report["rows"] if row["alpha"] == 0.45 and not row["immune"])
    control = next(row for row in report["rows"] if row["alpha"] == 0 and row["immune"])
    assert injected["metrics"]["readout_top1"]["mean"] >= 0.9
    assert injected["metrics"]["readout_top1"]["mean"] > report["chance"]["top1"]
    assert control["metrics"]["immune_any_alarm"]["mean"] <= 0.1


def test_real_tokens_do_not_reveal_concepts(backend, library):
    import re

    projection = BlindProjection(library.concepts)
    projection.event(Mode("telepathy", False, "Make tea.", 1, round_id=1, phase="generating"))
    clock = FakeClock()
    mixer = ForcedMixer(
        library.ids[0], alpha=0.45, median_norm=library.median_residual_norm, clock=clock
    )
    engine = Generator(backend, library, mixer)
    from nous.engine.events import Push

    for i in range(60):
        engine.push(Push(f"sim_{i:03}", library.ids[0], 0, "SIMULATED"))
    text = ""
    for event in engine.events(max_tokens=32):
        if isinstance(event, Token):
            text += projection.event(event).text
    tail = projection.finish_token()
    if tail:
        text += tail.text
    for concept in library.concepts:
        assert not re.search(
            r"(?<!\w)(?:"
            + "|".join(map(re.escape, (concept.id, concept.label, *concept.aliases)))
            + r")(?!\w)",
            text,
            re.IGNORECASE,
        )
