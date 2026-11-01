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
