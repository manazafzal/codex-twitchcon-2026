import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from nous.engine.events import Mode
from nous.server.app import APP_KEY
from nous.server.experience import Experience, RecordedDemo, make_experience_app
from nous.twitch.auth import TokenStore


def test_default_demo_full_round_without_network_model_or_twitch(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
    network = Mock(side_effect=AssertionError("An offline recording cannot make HTTP calls"))
    monkeypatch.setattr(aiohttp, "ClientSession", network)
    monkeypatch.setattr(TokenStore, "load", Mock(side_effect=AssertionError("No Twitch login")))
    elapsed = 0

    async def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    async def run():
        experience = Experience()
        experience.demo()
        assert experience.login["status"] == "idle"
        recording = RecordedDemo(sleep=sleep)
        output = []
        stream = recording.events()
        try:
            async for event in stream:
                output.append(event)
                if isinstance(event, Mode) and event.phase == "idle":
                    break
        finally:
            await stream.aclose()
        assert elapsed < 30
        assert any(isinstance(e, Mode) and e.phase == "guessing" for e in output)
        reveal = next(e for e in output if isinstance(e, Mode) and e.phase == "reveal")
        assert reveal.reveal and reveal.winner.startswith("sim_")
        badge = next(e for e in output if e.kind == "badge")
        assert badge.label == "SIMULATED ×40" and "RECORDING" in badge.quality
        assert not (tmp_path / "token.json").exists()

    asyncio.run(run())
    network.assert_not_called()


def test_welcome_bootstrap_is_private_cookie_is_guarded_and_demo_starts(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

    async def run():
        app = make_experience_app(token="private-run-code")
        async with TestClient(TestServer(app)) as client:
            page = await (await client.get("/welcome.html")).text()
            assert "Try the demo" in page and "Connect my Twitch" in page
            assert "private-run-code" not in page
            assert (await client.get("/welcome.js")).status == 200
            assert (await client.get("/api/welcome")).status == 403
            assert (await client.post("/api/demo", json={})).status == 403
            response = await client.post(
                "/api/bootstrap", headers={"Authorization": "Bearer private-run-code"}
            )
            assert response.status == 200
            assert response.cookies["nous_control"]["httponly"]
            assert response.cookies["nous_control"]["samesite"] == "Strict"
            assert (await client.get("/api/welcome")).status == 200
            assert (
                await client.post(
                    "/api/demo", json={}, headers={"Origin": "https://elsewhere.invalid"}
                )
            ).status == 403
            origin = str(client.make_url("/")).rstrip("/")
            response = await client.post("/api/demo", json={}, headers={"Origin": origin})
            assert response.status == 200 and (await response.json())["recording"]
            for _ in range(30):
                await asyncio.sleep(0.01)
                if app[APP_KEY].state.data["badge"]["quality"].startswith("RECORDING"):
                    break
            state = await (await client.get("/api/state")).json()
            assert "private-run-code" not in json.dumps(state)
            assert state["badge"]["label"] == "SIMULATED ×40"
            assert (await client.get("/demo_round.json")).status == 404
            assert (await client.get("/trace_data.js")).status == 404

    asyncio.run(run())


def test_setup_and_readme_are_beginner_first():
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text()
    assert readme.startswith("# Quick start in 3 steps")
    assert "setup.bat" in readme.split("\n## ", 1)[0]
    assert "powershell.exe" in (root / "setup.bat").read_text()
    script = (root / "tools/setup.ps1").read_text()
    assert "Downloading the AI brain (about 1 GB)..." in script
    assert "nous.install" in script and "'start'" in script
    assert "The recorded demo is still ready" not in script or "setup.bat" in script


def test_cli_default_demo_chooses_offline_experience(monkeypatch, tmp_path):
    from nous.cli import main
    from nous.server import experience

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NOUS_TWITCH_CLIENT_ID", raising=False)
    monkeypatch.setattr(TokenStore, "load", Mock(side_effect=AssertionError("No Twitch token")))
    calls = []
    monkeypatch.setattr(
        experience, "serve", lambda args, welcome: calls.append((args.command, welcome))
    )
    main(["demo", "--no-browser"])
    main(["start", "--no-browser"])
    assert calls == [("demo", False), ("start", True)]


def test_login_wizard_pending_success_and_recoverable_setup_error(monkeypatch, tmp_path):
    from test_twitch import FakeTwitch

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

    async def run():
        twitch = FakeTwitch()
        async with TestServer(twitch.app) as fake:
            experience = Experience(
                auth_base=str(fake.make_url("/oauth2")), helix_base=str(fake.make_url("/helix"))
            )
            app = make_experience_app(token="run-code", experience=experience)
            async with TestClient(TestServer(app)) as client:
                headers = {"Authorization": "Bearer run-code"}
                assert (
                    await client.post("/api/connect", json={"channel": "test"}, headers=headers)
                ).status == 400
                response = await client.post(
                    "/api/login", json={"app_code": "public-client"}, headers=headers
                )
                assert response.status == 200
                waiting = False
                for _ in range(140):
                    state = await (await client.get("/api/welcome", headers=headers)).json()
                    waiting |= state["status"] == "waiting"
                    if state["status"] == "connected":
                        break
                    await asyncio.sleep(0.05)
                assert waiting and state["status"] == "connected"
                assert experience.signed_in and (tmp_path / "token.json").exists()
                assert "access_token" not in json.dumps(
                    state
                ) and "refresh_token" not in json.dumps(state)
                assert (
                    await client.post("/api/connect", json={"channel": "test"}, headers=headers)
                ).status == 200
                for _ in range(40):
                    state = await (await client.get("/api/welcome", headers=headers)).json()
                    if state["status"] == "error":
                        break
                    await asyncio.sleep(0.01)
                assert state["status"] == "error" and "setup.bat" in state["message"]
                assert (await client.post("/api/demo", json={}, headers=headers)).status == 200

    asyncio.run(run())


def test_windows_permission_fallback_and_explicit_download(monkeypatch, tmp_path):
    import os
    import sys
    from types import SimpleNamespace

    from nous.install import download_model
    from nous.twitch.auth import Token

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
    monkeypatch.delattr(os, "fchmod", raising=False)
    store = TokenStore(tmp_path / "token.json")
    token = Token("test-access", "test-refresh", 9000)
    store.save(token)
    assert store.load() == token
    download = Mock()
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    download_model()
    arguments = download.call_args.kwargs
    assert arguments["repo_id"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert arguments["local_dir"] == tmp_path / "model"
    assert "*.safetensors" in arguments["allow_patterns"]


def test_connected_tick_waits_for_chat_and_demo_scores_stay_separate(monkeypatch, tmp_path):
    from test_twitch import FakeTwitch

    from nous.engine.events import Connection
    from nous.model import hf_backend
    from nous.model.mock_backend import MockBackend
    from nous.server.session import mock_library
    from nous.twitch.live import LiveSession

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NOUS_MODEL_PATH", str(tmp_path / "model"))
    (tmp_path / "model").mkdir()
    (tmp_path / "model/config.json").write_text("{}")
    mock_library().save(tmp_path / "concepts.npz")
    monkeypatch.setattr(hf_backend, "HFBackend", lambda **kwargs: MockBackend())

    async def fake_chat(self):
        yield Connection("twitch", "connected")
        await asyncio.Event().wait()

    monkeypatch.setattr(LiveSession, "events", fake_chat)

    async def run():
        twitch = FakeTwitch()
        async with TestServer(twitch.app) as fake:
            experience = Experience(
                auth_base=str(fake.make_url("/oauth2")), helix_base=str(fake.make_url("/helix"))
            )
            experience.client_id = "public-client"
            TokenStore(tmp_path / "token.json").save(twitch_token())
            experience.signed_in = True
            experience.login = {"status": "connected", "name": "bot"}
            experience.board.add("viewer", "Viewer", 7)
            app = make_experience_app(token="run-code", experience=experience)
            async with TestClient(TestServer(app)) as client:
                headers = {"Authorization": "Bearer run-code"}
                response = await client.post(
                    "/api/connect", json={"channel": "streamer"}, headers=headers
                )
                assert response.status == 200
                for _ in range(100):
                    status = await (await client.get("/api/welcome", headers=headers)).json()
                    if status["status"] == "live":
                        break
                    await asyncio.sleep(0.02)
                assert status["status"] == "live"
                assert app[APP_KEY].leaderboard is experience.board
                await client.post("/api/demo", json={}, headers=headers)
                assert app[APP_KEY].leaderboard is not experience.board
                assert experience.board.stream["viewer"]["points"] == 7

    asyncio.run(run())


def twitch_token():
    import time

    from nous.twitch.auth import Token

    return Token("access-0", "refresh-0", time.time() + 3600, "200", "bot")


def test_source_switch_stops_previous_owner_and_renews_blind_aliases(monkeypatch, tmp_path):
    from nous.concepts.library import load_concepts
    from nous.engine.events import Token

    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

    async def run():
        experience = Experience()
        active, peak = 0, 0

        async def source():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                yield Mode(
                    "telepathy",
                    False,
                    "Make tea.",
                    0,
                    phase="generating",
                    injection="ocean",
                    round_id=1,
                )
                yield Token(
                    0,
                    "A cup. ",
                    "ocean",
                    {"scores": {c.id: 0 for c in load_concepts()}, "top": "ocean", "margin": 0},
                    "ocean",
                )
                await asyncio.Event().wait()
            finally:
                active -= 1

        app = make_experience_app(experience=experience)
        async with TestClient(TestServer(app)) as client:
            experience.use(source)
            for _ in range(100):
                if app[APP_KEY].state.data["tokens"]:
                    break
                await asyncio.sleep(0.01)
            first = dict(app[APP_KEY].presentation.strict.ids)
            old_version = experience.version
            experience.use(source)
            assert experience.version > old_version
            for _ in range(100):
                current = app[APP_KEY].presentation.strict.ids
                if current != first and app[APP_KEY].state.data["tokens"]:
                    break
                await asyncio.sleep(0.01)
            assert current != first and peak == 1
            public = await (await client.get("/api/state")).json()
            assert public["mode"]["injection"] is None
            assert all(key.startswith("voc") for key in public["tokens"][0]["readout"]["scores"])
        assert active == 0

    asyncio.run(run())


def test_reveal_restores_real_capped_shares_after_hidden_aggregate():
    from nous.concepts.library import load_concepts
    from nous.engine.events import Layout, Tick
    from nous.server.app import Server

    async def run():
        server = Server(concepts=load_concepts())
        await server.publish(Layout({c.id: [0, 0] for c in load_concepts()}))
        await server.publish(Mode("telepathy", False, "Make tea.", 1, phase="armed", round_id=1))
        shares = {"space": 0.5, "jazz": 0.5, "Neutral": 0}
        await server.publish(Tick(shares, 1, [], 0))
        assert server.state.data["tick"]["shares"] == {"Neutral": 0, "?": 1}
        await server.publish(
            Mode("telepathy", False, "Make tea.", 1, phase="reveal", reveal="ocean", round_id=1)
        )
        assert server.state.data["tick"]["shares"] == shares
        assert all(v <= 0.75 for key, v in shares.items() if key != "Neutral")

    asyncio.run(run())
