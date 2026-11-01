"""Deterministic test-model evidence only; no trained-model quality claim."""

import asyncio
import json
import re
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from nous.concepts.library import Concept, ConceptLibrary
from nous.concepts.policy import prohibited, validate_name
from nous.concepts.queue import TopicQueue
from nous.concepts.topics import TopicBuilder, load_examples, save_result
from nous.engine.commands import Propose
from nous.engine.events import Mode, Token
from nous.engine.immune import clamp
from nous.model.backend import State
from nous.server.app import Server
from nous.server.session import Session
from nous.twitch.parse import ChatParser


class TopicModel:
    num_layers, hidden_size, injection_layer, readout_layer = 12, 32, 7, 11
    eos_token_id = 0
    labels = ("ocean", "space", "jazz", "comet")

    def __init__(self):
        self.tokens = {}
        self.context = ""

    def index(self, text):
        return next(
            (
                i
                for i, word in enumerate(self.labels)
                if re.search(r"\b" + word + r"\b", text, re.IGNORECASE)
            ),
            0,
        )

    def sample(self, logits, temperature, top_p, rng):
        if logits[1]:
            return 0
        nonce = int(rng.integers(1, 2**60))
        label = self.labels[int(logits[0])]
        self.tokens[nonce] = (
            label + " water tea morning routine bag bicycle tyre school day shirt lunch desk "
            "tidy clean room pack prepare daily cup warm rest clothes meal plan shoes notes "
            "books home choose wash food time careful simple steps " + str(nonce)
        )
        return nonce

    def decode(self, tokens):
        return " ".join(self.tokens[token] for token in tokens)

    def state(self, prompt, inject=None, defend=None, *, done=False):
        h = np.eye(32)[self.index(prompt)].copy()
        if inject is not None:
            h += inject
        before = h.copy()
        pre = post = None
        if defend is not None:
            h, pre, post = clamp(h, defend)
        idx = int(np.argmax(h[:4]))
        return State(
            np.array([idx, float(done)]),
            h,
            prompt,
            2 if done else 1,
            before,
            pre,
            post,
            {7: before, 11: h},
        )

    def prefill(self, prompt, inject=None, defend=None, *, inject_prefill=True):
        return self.state(prompt, inject if inject_prefill else None, defend)

    def step(self, state, token, inject=None, defend=None):
        result = self.state(self.decode([token]), inject, defend, done=True)
        return result.logits, result.readout_hidden, result

    def embed_texts(self, texts, layer):
        return np.stack([np.eye(32)[self.index(text)] for text in texts])


@pytest.fixture
def topic_builder():
    model = TopicModel()
    concepts = [Concept(name, name.title(), i, ()) for i, name in enumerate(model.labels[:3])]
    library = ConceptLibrary(
        concepts,
        np.eye(32)[:3],
        np.eye(32)[:3],
        np.zeros(32),
        np.ones(3),
        {
            "model": "TINY MODEL / CI",
            "variant": "others",
            "injection_layer": 7,
            "readout_layer": 11,
            "probe_layers": [7, 11],
            "median_residual_norm": 26.78,
        },
    )
    return TopicBuilder(model, library)


def test_good_topic_passes_every_gate_and_refits_the_whole_catalog(topic_builder, tmp_path):
    result = topic_builder.build("comet")
    assert result.report["status"] == "accepted", result.report["reasons"]
    assert all(c["passed"] for c in result.report["checks"].values())
    assert result.report["checks"]["heldout_top1"]["n"] == 12
    library = result.library
    assert library is not None
    assert library.ids == ("ocean", "space", "jazz", "comet")
    assert library.hash != topic_builder.base.hash
    assert library.readout_v4["weights"].shape == (4, 64)
    assert library.alarm_thresholds.shape == (4,)
    assert set(library.layout()) == set(library.ids)
    assert library.provenance["readout_fit"]["n"] == 48
    assert library.provenance["readout_v4"]["partitions"]["train"]["n"] == 264
    origin = result.report["origin"]
    assert len(origin["texts"]) == len(set(origin["texts"])) == 24
    assert all(
        len(a.split()) == len(b.split())
        for a, b in zip(origin["texts"], origin["neutral_texts"], strict=True)
    )
    save_result(result, tmp_path)
    loaded = ConceptLibrary.load(tmp_path / "library.npz")
    assert loaded.hash == library.hash
    assert json.loads((tmp_path / "quality.json").read_text())["status"] == "accepted"


def test_random_examples_fail_heldout_check_and_never_publish(topic_builder, tmp_path):
    rng = np.random.default_rng(9)
    words = ["paper", "shelf", "chair", "door", "mat", "lamp"]
    examples = [" ".join(rng.choice(words, 10)) + f" {i}" for i in range(24)]
    before = topic_builder.base.hash
    result = topic_builder.build("comet", examples=examples)
    assert result.report["status"] == "rejected"
    assert result.report["checks"]["heldout_top1"]["value"] < 0.8
    assert result.library is None and topic_builder.base.hash == before
    assert result.report["origin"]["texts"] == examples
    (tmp_path / "library.npz").write_bytes(b"stale candidate")
    save_result(result, tmp_path)
    assert not (tmp_path / "library.npz").exists()


def test_pasted_examples_preserved_and_duplicates_cannot_cross_the_split(topic_builder, tmp_path):
    texts = [f"  comet sample {i} stays as pasted.  " for i in range(4)]
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(texts))
    assert load_examples(path) == texts
    repeated = [texts[0]] * 24
    result = topic_builder.build("comet", examples=repeated)
    assert result.report["status"] == "rejected"
    assert result.report["origin"]["texts"] == repeated
    assert result.report["checks"]["heldout_top1"]["status"] == "unrun"


def test_policy_matches_repository_rules_without_embedding_them_in_assets():
    root = Path(__file__).resolve().parents[1]
    rule = (root / "AGENTS.md").read_text().split("Do NOT use:", 1)[1].split("\n2.", 1)[0]
    for term in re.findall(r'"([^"]+)"', rule):
        assert prohibited(term.upper())
        assert prohibited(term + "ed")
    for word in ["comet", "aurora", "spice"]:
        assert validate_name(word, chat=True) == word
    for word in ["ab", "a" * 21, "two words", "café", "../word"]:
        with pytest.raises(ValueError):
            validate_name(word, chat=True)


def test_queue_cooldowns_capacity_and_rejected_topics_stay_private(tmp_path):
    queue = TopicQueue(tmp_path / "topics")
    assert queue.offer("comet", "u", 0, set())
    assert not queue.offer("aurora", "u", 15, set())
    assert not queue.offer("aurora", "other", 1, set())
    assert not queue.offer("comet", "other", 20, set())
    assert not queue.offer("ocean", "other", 20, {"ocean"})
    result = queue.build_next()
    assert result.report["status"] == "rejected"
    assert not (tmp_path / "concepts.npz").exists()
    assert queue.added == 0


def notification(text, ident="m"):
    return {
        "metadata": {"message_type": "notification"},
        "payload": {
            "subscription": {"type": "channel.chat.message", "version": "1"},
            "event": {
                "broadcaster_user_id": "owner",
                "chatter_user_id": "viewer",
                "chatter_user_name": "Friend",
                "message_id": ident,
                "message": {"text": text},
            },
        },
    }


def test_propose_parser_and_blind_acknowledgement():
    session = Session()
    parser = ChatParser(session.library.concepts, bot_id="bot", broadcaster_id="owner")
    command = parser.parse(notification("!propose COMET"))
    assert isinstance(command, Propose) and command.name == "comet"
    assert parser.parse(notification("!propose café", "bad")) is None
    assert parser.parse(notification("!propose two words", "more")) is None
    session.current_mode = "telepathy"
    session.telepathy.arm(set())
    session.pending.put_nowait(command)
    messages = [e.message for e in session.drain() if hasattr(e, "message")]
    assert messages and all("comet" not in text.casefold() for text in messages)
    assert session.topics.pending == __import__("collections").deque(["comet"])


def test_catalog_refresh_adds_masking_and_refuses_changes_while_blind(topic_builder):
    async def run():
        server = Server(concepts=topic_builder.base.concepts)
        expanded = [*topic_builder.base.concepts, Concept("comet", "Comet", 3, ())]
        await server.update_catalog(expanded)
        await server.publish(Mode("telepathy", False, "Make tea", 1, phase="armed", round_id=1))
        await server.publish(
            Token(0, "com", None, {"scores": {"comet": 5.0}, "top": "comet", "margin": 1.0}, None)
        )
        await server.publish(
            Token(
                1,
                "et is here ",
                None,
                {"scores": {"comet": 5.0}, "top": "comet", "margin": 1.0},
                None,
            )
        )
        public = json.dumps(server.state.snapshot().to_dict()).casefold()
        assert "comet" not in public
        with pytest.raises(RuntimeError):
            await server.update_catalog(expanded)

    asyncio.run(run())


def test_serialized_backend_prevents_overlap_and_can_stop_a_build():
    import time
    from concurrent.futures import ThreadPoolExecutor

    from nous.model.serialized import SerializedBackend

    class Backend:
        active = 0
        peak = 0

        def step(self):
            self.active += 1
            self.peak = max(self.peak, self.active)
            time.sleep(0.005)
            self.active -= 1

    backend = Backend()
    game = SerializedBackend(backend)
    stop = Event()
    builder = SerializedBackend(backend, game.lock, stop)
    with ThreadPoolExecutor(2) as pool:
        jobs = [pool.submit(wrapper.step) for wrapper in [game, builder] * 5]
        for job in jobs:
            job.result()
    assert backend.peak == 1
    stop.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        builder.step()
    game.step()


@pytest.mark.realmodel
def test_add_one_real_concept_end_to_end(tmp_path):
    import os

    if (
        os.getenv("NOUS_REAL") != "1"
        or not os.getenv("NOUS_LIBRARY")
        or not os.getenv("NOUS_MODEL_PATH")
    ):
        pytest.skip("Requires explicitly enabled local trained weights and verified library")
    from nous.model.hf_backend import HFBackend

    base = ConceptLibrary.load(Path(os.environ["NOUS_LIBRARY"]))
    result = TopicBuilder(HFBackend(local_path=os.environ["NOUS_MODEL_PATH"]), base).build("comet")
    save_result(result, tmp_path)
    report = json.loads((tmp_path / "quality.json").read_text())
    assert report["status"] in {"accepted", "rejected"}
    assert all(c["status"] in {"run", "unrun"} for c in report["checks"].values())
    if report["status"] == "accepted":
        assert all(c["status"] == "run" and c["passed"] for c in report["checks"].values())
        assert ConceptLibrary.load(tmp_path / "library.npz").hash == report["library_hash"]
    else:
        assert not (tmp_path / "library.npz").exists()


@pytest.mark.parametrize(
    "gate,value",
    [("heldout_top1", 0.79), ("max_cosine", 0.61), ("injection_gain", 0.09), ("task_kept", 0.59)],
)
def test_publication_rechecks_the_exact_bars(topic_builder, tmp_path, gate, value):
    from nous.concepts.topics import approved

    result = topic_builder.build("comet", count=4)
    assert approved(result)
    result.report["checks"][gate].update(value=value, passed=True)
    assert not approved(result)
    save_result(result, tmp_path)
    assert result.report["status"] == "rejected"
    assert not (tmp_path / "library.npz").exists()


def test_failed_recalibration_keeps_a_qualified_candidate_private(topic_builder, monkeypatch):
    def fail(library):
        raise ValueError("Fresh calibration unavailable")

    monkeypatch.setattr(topic_builder, "recalibrate", fail)
    result = topic_builder.build("comet", count=4)
    assert all(c["passed"] for c in result.report["checks"].values())
    assert result.report["status"] == "rejected" and result.library is None


def test_installation_waits_for_completed_secret_round(topic_builder):
    result = topic_builder.build("comet", count=4)
    session = Session(backend=topic_builder.backend, library=topic_builder.base)
    session.telepathy.arm(set())
    with pytest.raises(RuntimeError, match="boundary"):
        session.install_library(result.library)
    assert session.library.hash == topic_builder.base.hash
    session.telepathy.cancel()
    session.install_library(result.library)
    assert session.engine.readout.library is result.library
    assert set(session.engine.atlas.points) == set(result.library.ids)
    assert session.telepathy.concepts == result.library.concepts


def test_pack_reports_are_explicit_and_cannot_publish_missing_measurements():
    root = Path(__file__).resolve().parents[1]
    for name in ["cosmos", "kitchen", "mythic"]:
        directory = root / "data/packs" / name
        pack = json.loads((directory / "pack.json").read_text())
        assert len(pack["concepts"]) == 8
        for entry in pack["concepts"]:
            report = json.loads((directory / entry["report"]).read_text())
            assert report["status"] in {"accepted", "rejected"}
            if any(c["status"] == "unrun" for c in report["checks"].values()):
                assert report["status"] == "rejected" and report["reasons"]
                assert not (directory / entry["name"] / "library.npz").exists()


def test_cli_writes_a_rejection_without_weights_or_a_token(tmp_path):
    from nous.cli import main

    main(
        [
            "concept",
            "add",
            "comet",
            "--library",
            str(tmp_path / "missing.npz"),
            "--model-path",
            str(tmp_path / "no-weights"),
            "--output",
            str(tmp_path),
        ]
    )
    report = json.loads((tmp_path / "comet/quality.json").read_text())
    assert report["status"] == "rejected" and report["source"] == "unavailable"
    assert all(c["n"] == 0 and c["value"] is None for c in report["checks"].values())


def test_background_build_publishes_only_between_answers_and_records_catalog(
    topic_builder, tmp_path, monkeypatch
):
    from dataclasses import asdict

    from nous.engine.events import Round
    from nous.engine.mixer import FakeClock
    from nous.replay.player import Player
    from nous.replay.recorder import Recorder
    from nous.sim.crowd import Crowd

    result = topic_builder.build("comet", count=4)
    clock = FakeClock()
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        clock.advance(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    session = Session(
        backend=topic_builder.backend,
        library=topic_builder.base,
        crowd=Crowd(twitch_connected=True),
        clock=clock,
    )
    session.topics = TopicQueue(tmp_path / "topics", topic_builder)
    session.topics.pending.append("comet")

    def ready(name):
        return result

    monkeypatch.setattr(session.topics, "build", ready)
    session.recorder = Recorder(tmp_path / "round.jsonl", session.metadata(), clock=clock)

    async def run():
        stream = session.events()
        try:
            for _ in range(200):
                event = await anext(stream)
                if isinstance(event, Round) and event.phase == "catalog":
                    assert not session.answer_running
                    assert session.library.hash == result.library.hash
                    assert json.loads(event.message)["concepts"] == json.loads(
                        json.dumps([asdict(c) for c in result.library.concepts])
                    )
                    return
            pytest.fail("Ready candidate did not publish at a round boundary")
        finally:
            await stream.aclose()

    asyncio.run(run())
    replay = Player(tmp_path / "round.jsonl")
    assert any(row.get("event", {}).get("phase") == "catalog" for row in replay.rows)
    with pytest.raises(ValueError, match="--frames"):
        list(replay.engine_events(session.engine, FakeClock()))


def test_catalog_event_rebuilds_public_snapshot_and_hides_again_for_guessing(topic_builder):
    from dataclasses import asdict

    from nous.engine.events import Round

    expanded = [*topic_builder.base.concepts, Concept("comet", "Comet", 3, ())]
    update = Round(
        "war",
        "catalog",
        0,
        json.dumps({"concepts": [asdict(c) for c in expanded], "library_hash": "test-only"}),
    )

    async def run():
        server = Server(concepts=topic_builder.base.concepts)
        await server.publish(update)
        assert any(c["id"] == "comet" for c in server.state.snapshot().state["concepts"])
        await server.publish(Mode("telepathy", False, "Make tea", 1, phase="armed"))
        assert "comet" not in json.dumps(server.state.snapshot().to_dict()).casefold()
        with pytest.raises(RuntimeError):
            await server.publish(update)

    asyncio.run(run())


def test_overlay_renders_dynamic_topic_labels_without_adding_bonus_to_play_strip(monkeypatch):
    from tools.overlay_browser import CHROME, Browser

    if not CHROME:
        pytest.skip("Local Chrome is unavailable; no download")
    from nous.engine.events import Round, Tick

    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")
    update = Round(
        "war",
        "catalog",
        0,
        json.dumps(
            {
                "concepts": [
                    {"id": "comet", "label": "Comet", "aliases": ["comet"], "color_index": 0}
                ]
            }
        ),
    )
    tick = Tick({"comet": 0.75, "Neutral": 0.25}, 1, [], 0)

    async def run():
        async with Browser("manual&scale=.5&nogl") as browser:
            await browser.evaluate("NousOverlay.fixture.pause()")
            await browser.evaluate(f"NousOverlay.dispatch({json.dumps(update.to_dict())})")
            await browser.evaluate(f"NousOverlay.dispatch({json.dumps(tick.to_dict())})")
            await browser.evaluate("NousOverlay.step(2)")
            content = await browser.evaluate("document.body.innerText")
            assert "COMET" in content.upper()
            assert "!propose" not in content
            assert not browser.errors

    asyncio.run(run())


def test_repeated_proposals_do_not_repeat_bot_replies():
    from nous.engine.events import Round

    session = Session()
    for _ in range(1000):
        session.pending.put_nowait(Propose("comet", "Friend", "same-viewer"))
    replies = [e for e in session.drain() if isinstance(e, Round)]
    assert len(replies) == 1
    assert len(session.topics.pending) == 1


def test_bonus_command_preserves_existing_command_routes():
    from nous.engine.commands import Rank, SetMode, StartRound
    from nous.engine.events import Round

    session = Session()
    for command in [
        Propose("comet", "Friend", "viewer"),
        Rank("Friend", "viewer"),
        SetMode("attack"),
        StartRound(),
    ]:
        session.pending.put_nowait(command)
    events = session.drain()
    assert any(isinstance(e, Round) and e.phase == "rank" for e in events)
    assert any(isinstance(e, Round) and "Testing 'comet'" in e.message for e in events)
    assert any(isinstance(e, Round) and "New round starting" in e.message for e in events)
    assert session.mode == "telepathy"
