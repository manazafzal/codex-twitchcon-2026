import asyncio
import json

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from thoughtquake.engine.atlas import AtlasSignals, pca_points
from thoughtquake.engine.events import Layout, Mode, Tick, Token, event_from_dict
from thoughtquake.model.backend import State
from thoughtquake.server.app import APP_KEY, create_app
from thoughtquake.server.presentation import Presentation
from thoughtquake.server.session import mock_library


def test_pca_is_centered_deterministic_and_normalized():
    points = np.array([[1, 0, 0], [-1, 0, 0], [0, 2, 0], [0, -2, 0]])
    result = pca_points(points, ("a", "b", "c", "d"))
    assert result == {"a": [0, 1], "b": [0, -1], "c": [1, 0], "d": [-1, 0]}
    assert result == pca_points(points, ("a", "b", "c", "d"))


def test_signals_are_measured_and_missing_calibration_is_not_sd():
    library = mock_library()
    atlas = AtlasSignals(library)
    before, after = np.zeros(32), np.ones(32)
    atlas.begin(before)
    state = State(np.zeros(2), after, None, 0)
    signal = atlas.observe(after, state)
    assert signal["residual"] == pytest.approx(np.sqrt(32))
    assert signal["median"] == signal["residual"]
    assert signal["drive"] == 1
    cosine = np.ones(30) / np.sqrt(32)
    expected = (cosine - library.readout_mean) / library.readout_std
    np.testing.assert_allclose(list(signal["z"].values()), expected)
    library.readout_mean = library.readout_std = None
    assert not atlas.observe(after, state)["calibrated"]
    assert set(atlas.observe(after, state)["z"].values()) == {0}


def test_layout_and_token_sky_schema_reject_nonfinite():
    with pytest.raises(ValueError):
        event_from_dict(Layout({"a": [float("nan"), 0]}).to_dict())
    with pytest.raises(ValueError):
        event_from_dict(Layout({"a": [2, 0]}).to_dict())
    signal = AtlasSignals(mock_library()).observe(
        np.ones(32), State(np.zeros(2), np.ones(32), None, 0)
    )
    token = Token(0, "tea", None, {"scores": {}, "top": None, "margin": 0}, None, signal)
    assert event_from_dict(token.to_dict()) == token
    signal["drive"] = float("inf")
    with pytest.raises(ValueError):
        event_from_dict(token.to_dict())


def test_blind_sky_and_snapshot_do_not_reveal_identity():
    library = mock_library()
    public = Presentation()
    points = AtlasSignals(library).points
    public.event(Layout(points))
    public.event(Mode("telepathy", False, "Tea", 1, round_id=7))
    blind = public.layout()
    assert not set(points).intersection(blind.points)
    assert not blind.alias
    signal = AtlasSignals(library).observe(np.ones(32), State(np.zeros(2), np.ones(32), None, 0))
    token = public.event(
        Token(
            0,
            "tea",
            library.ids[0],
            {"scores": dict.fromkeys(library.ids, 0.2), "top": library.ids[0], "margin": 0},
            library.ids[0],
            signal,
        )
    )
    assert not set(points).intersection(token.sky["z"])
    assert set(token.sky["z"]) == set(blind.points)
    public.event(
        Mode("telepathy", False, "Tea", 1, round_id=7, phase="reveal", reveal=library.ids[0])
    )
    revealed = public.layout()
    assert set(revealed.alias) == set(blind.points)
    assert {key: points[value] for key, value in revealed.alias.items()} == revealed.points


def test_fixtures_are_opt_in_and_fonts_are_allowlisted(monkeypatch):
    async def run():
        async with TestClient(TestServer(create_app())) as client:
            for path in ("fixture.html", "fixture.js", "trace_data.js"):
                assert (await client.get("/" + path)).status == 404
            assert (await client.get("/fonts/CormorantGaramond.ttf")).status == 200
            assert (await client.get("/fonts/unknown.ttf")).status == 404
            server = client.app[APP_KEY]
            library = mock_library()
            await server.publish(Layout(AtlasSignals(library).points))
            await server.publish(Mode("telepathy", False, "Tea", 1, round_id=1))
            await server.publish(Tick({library.ids[0]: 0.5, "Neutral": 0.5}, 1, [], 0))
            data = await (await client.get("/api/state")).json()
            assert not set(library.ids).intersection(data["layout"]["points"])
            assert library.ids[0] not in data["tick"]["shares"]
            assert json.loads(json.dumps(data)) == data

    monkeypatch.delenv("THOUGHTQUAKE_DEV_FIXTURES", raising=False)
    asyncio.run(run())


def test_calibration_library_roundtrip_and_hash(tmp_path):
    from thoughtquake.concepts.library import ConceptLibrary

    library = mock_library()
    path = tmp_path / "atlas.npz"
    library.save(path)
    restored = ConceptLibrary.load(path)
    assert restored.hash == library.hash
    np.testing.assert_array_equal(restored.readout_mean, library.readout_mean)
    np.testing.assert_array_equal(restored.readout_std, library.readout_std)
    restored.readout_mean[0] += 1
    assert restored.hash != library.hash


def test_glow_z_uses_the_windowed_readout_scores():
    library = mock_library()
    atlas = AtlasSignals(library)
    hidden = np.ones(32)
    state = State(np.zeros(2), hidden, None, 0)
    scores = dict.fromkeys(library.ids, 0.25)
    signal = atlas.observe(hidden, state, scores)
    np.testing.assert_allclose(
        list(signal["z"].values()), (0.25 - library.readout_mean) / library.readout_std
    )
