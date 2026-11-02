import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aiohttp.test_utils import TestServer
from test_easy_start import twitch_token
from test_twitch import FakeTwitch

from nous import cli, config
from nous.concepts.library import ConceptLibrary
from nous.model.hf_backend import HFBackend
from nous.model.mock_backend import MockBackend
from nous.server.experience import Experience
from nous.twitch.auth import TokenStore

ROOT = Path(__file__).parents[1]
SUPPLIED_SHA256 = "ee70c50cae57f841423160515dcd8d43bee52a6265b4ace9660b645bf1fb7e00"


@pytest.fixture
def fresh_home(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NOUS_MODEL_PATH", raising=False)
    monkeypatch.delenv("NOUS_DEVICE", raising=False)
    return tmp_path


def test_fresh_clone_uses_exact_supplied_library_and_preserves_custom_override(
    fresh_home, monkeypatch
):
    monkeypatch.chdir(fresh_home)
    bundled = config.bundled_library_path()
    assert bundled == ROOT / "library/nous-fitted.npz"
    assert hashlib.sha256(bundled.read_bytes()).hexdigest() == SUPPLIED_SHA256
    assert config.library_path() == bundled
    library = ConceptLibrary.load(bundled)
    assert len(library.ids) == 30 and library.readout_v4
    assert library.config["readout_v4_margin_threshold"] == pytest.approx(355.85, abs=0.005)
    assert library.config["injection_layer"] == 16 and library.config["readout_layer"] == 20
    library.config["custom"] = True
    library.save(config.user_library_path())
    assert config.library_path() == fresh_home / "concepts.npz"
    assert ConceptLibrary.load(config.library_path()).config["custom"]
    assert hashlib.sha256(bundled.read_bytes()).hexdigest() == SUPPLIED_SHA256


def test_backend_uses_setup_folder_and_cpu_even_if_a_graphics_card_exists(fresh_home, monkeypatch):
    config.model_dir().mkdir()
    (config.model_dir() / "config.json").write_text("{}")
    devices = []
    model = SimpleNamespace(to=lambda device: devices.append(device) or model, eval=lambda: model)
    tokenizer, loader = Mock(return_value=object()), Mock(return_value=model)
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer),
            AutoModelForCausalLM=SimpleNamespace(from_pretrained=loader),
        ),
    )
    monkeypatch.setattr(HFBackend, "_configure", lambda self, model: None)
    HFBackend()
    assert devices == ["cpu"]
    tokenizer.assert_called_once_with(str(fresh_home / "model"), local_files_only=True)
    loader.assert_called_once_with(str(fresh_home / "model"), local_files_only=True)
    monkeypatch.setenv("NOUS_DEVICE", "auto")
    HFBackend()
    assert devices[-1] == "cuda"


class FakeHF(MockBackend):
    hidden_size, num_layers, injection_layer, readout_layer = 896, 24, 16, 20


def live_cli(monkeypatch):
    monkeypatch.setenv("NOUS_TWITCH_CLIENT_ID", "public-client")
    monkeypatch.setattr(TokenStore, "load", lambda self: twitch_token())
    calls, sessions = [], []

    def backend(**kwargs):
        calls.append(kwargs)
        return FakeHF()

    class Live:
        def __init__(self, session, *args, **kwargs):
            sessions.append(session)

        async def events(self):
            if False:
                yield

    monkeypatch.setattr("nous.model.hf_backend.HFBackend", backend)
    monkeypatch.setattr("nous.twitch.live.LiveSession", Live)
    monkeypatch.setattr(cli.web, "run_app", lambda *args, **kwargs: None)
    return calls, sessions


def test_run_defaults_to_real_fitted_library_and_setup_model_folder(fresh_home, monkeypatch):
    calls, sessions = live_cli(monkeypatch)
    cli.main(["run", "--channel", "streamer", "--no-browser"])
    assert calls == [{"local_path": str(fresh_home / "model")}]
    supplied = ConceptLibrary.load(config.bundled_library_path())
    assert sessions[0].library.hash == supplied.hash
    assert sessions[0].source == "LIVE" and not sessions[0].crowd.enabled
    cli.main(["run", "--channel", "streamer", "--mock", "--no-browser"])
    assert len(calls) == 1
    assert sessions[1].library.config["model"] == "mock"


def test_run_honours_explicit_library_and_model_path(fresh_home, monkeypatch):
    calls, sessions = live_cli(monkeypatch)
    library = ConceptLibrary.load(config.bundled_library_path())
    library.config["custom"] = True
    path = fresh_home / "custom.npz"
    library.save(path)
    model = fresh_home / "other-model"
    cli.main(["run", "--channel", "streamer", "--library", str(path), "--model-path", str(model)])
    assert calls == [{"local_path": str(model)}]
    assert sessions[0].library.hash == library.hash


def test_run_missing_model_has_setup_instructions_and_never_substitutes_mock(
    fresh_home, monkeypatch, capsys
):
    monkeypatch.setenv("NOUS_TWITCH_CLIENT_ID", "public-client")
    monkeypatch.setattr(TokenStore, "load", lambda self: twitch_token())
    serve = Mock(side_effect=AssertionError("A missing model cannot start a live engine"))
    monkeypatch.setattr(cli.web, "run_app", serve)
    with pytest.raises(SystemExit) as caught:
        cli.main(["run", "--channel", "streamer", "--no-browser"])
    assert caught.value.code == 1
    error = capsys.readouterr().err
    assert str(fresh_home / "model") in error
    assert "setup.bat" in error and "python -m nous.install" in error
    assert "Traceback" not in error
    serve.assert_not_called()


def test_connect_uses_bundled_fitted_library_without_building_or_fitting(fresh_home, monkeypatch):
    from nous.engine.events import Connection
    from nous.twitch.live import LiveSession

    config.model_dir().mkdir()
    (config.model_dir() / "config.json").write_text("{}")
    calls = []
    monkeypatch.setattr(
        "nous.model.hf_backend.HFBackend", lambda **kwargs: calls.append(kwargs) or FakeHF()
    )
    forbidden = Mock(side_effect=AssertionError("Connect must use the supplied fitted artifact"))
    monkeypatch.setattr("nous.concepts.builder.build_library", forbidden)
    monkeypatch.setattr("nous.evaluation.fit_readout", forbidden)

    async def chat(self):
        yield Connection("twitch", "connected")

    monkeypatch.setattr(LiveSession, "events", chat)

    async def run():
        twitch = FakeTwitch()
        async with TestServer(twitch.app) as fake:
            TokenStore(fresh_home / "token.json").save(twitch_token())
            experience = Experience(
                auth_base=str(fake.make_url("/oauth2")), helix_base=str(fake.make_url("/helix"))
            )
            experience.client_id = "public-client"
            await experience.connect("streamer")
            supplied = ConceptLibrary.load(config.bundled_library_path())
            assert experience.session.library.hash == supplied.hash
            assert experience.session.library.readout_v4
            assert not config.user_library_path().exists()
            assert calls == [{"local_path": str(fresh_home / "model")}]
            assert [e.state async for e in experience.factory()] == ["connected"]

    asyncio.run(run())
    forbidden.assert_not_called()


def test_setup_passes_complete_argument_arrays_and_readme_states_cpu_default():
    script = (ROOT / "tools/setup.ps1").read_text()
    calls = [
        line
        for line in script.splitlines()
        if "Run-Checked " in line and not line.startswith("function")
    ]
    assert calls and all("-Program " in line and "-Arguments @(" in line for line in calls)
    assert "& $Program @Arguments" in script
    assert "'.[model]'" in script and "'nous.install'" in script and "'start'" in script
    intro = (ROOT / "README.md").read_text().split("## Meet NOUS", 1)[0]
    assert intro.startswith("# Quick start in 3 steps") and "CPU by default" in intro


def test_reported_results_remain_separate_from_registered_unrun_cells():
    note = (ROOT / "docs/REAL_MODEL_RESULTS.md").read_text()
    paper = (ROOT / "docs/paper.md").read_text()
    assert "94.2% (91.7 to 96.4%" in note and "192 of 192" in note
    assert "94.2% (91.7 to 96.4%" in paper
    assert "earlier library" in note and "not run" in note
    for path in (ROOT / "research/tables").glob("*.json"):
        rows = json.loads(path.read_text())
        assert all(row["status"] == "unrun" for row in rows)


def test_eval_also_defaults_to_the_shipped_fitted_library(fresh_home, monkeypatch):
    calls = []
    monkeypatch.setattr("nous.model.hf_backend.HFBackend", lambda **kwargs: FakeHF())
    monkeypatch.setattr(
        "nous.evaluation.evaluate", lambda backend, library, **kwargs: calls.append(library) or {}
    )
    monkeypatch.setattr("nous.evaluation.write_report", lambda *args: None)
    cli.main(["eval", "--output", str(fresh_home / "results")])
    assert calls[0].hash == ConceptLibrary.load(config.bundled_library_path()).hash
    monkeypatch.setenv("NOUS_MODEL_PATH", "")
    assert config.model_dir() == fresh_home / "model"
