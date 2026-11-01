import asyncio

from aiohttp.test_utils import TestClient, TestServer

from nous.engine.events import Immune, Mode, Tamper, Token
from nous.server.app import APP_KEY, create_app
from nous.server.presentation import Presentation
from nous.server.state import ViewState


def token():
    return Token(
        0,
        "A quiet cup of tea.",
        "cats",
        {"scores": {"cats": 0.9, "ocean": 0.2, "space": 0.1}, "top": "cats", "margin": 0.7},
        "cats",
    )


def test_secret_masking_covers_tokens_and_raw_snapshots_before_reveal():
    projector = Presentation()
    mode = Mode(
        "telepathy",
        False,
        "Make tea.",
        0,
        phase="generating",
        injection="cats",
        candidates=("cats", "ocean", "space"),
    )
    hidden = projector.event(mode)
    assert hidden.injection is None and hidden.candidates == ("A", "B", "C")
    hidden_token = projector.event(token())
    assert hidden_token.applied is hidden_token.color is None
    assert hidden_token.readout == {
        "scores": {"A": 0.9, "B": 0.2, "C": 0.1},
        "top": "A",
        "margin": 0.7,
    }
    assert projector.event(Tamper(("cats",), 0.5)).concepts == ("hidden concept",)
    state = ViewState()
    state.apply(mode)
    state.apply(token())
    public = Presentation().event(state.snapshot()).state
    assert public["mode"]["injection"] is None
    assert public["tokens"][0]["color"] is None
    assert set(public["readouts"][0]) == {"A", "B", "C"}
    reveal = projector.event(
        Mode(
            "telepathy",
            False,
            "Make tea.",
            0,
            phase="reveal",
            reveal="cats",
            injection="cats",
            probe_top="ocean",
            winner="Friend",
        )
    )
    assert reveal.reveal == "cats" and reveal.probe_top == "ocean" and reveal.winner == "Friend"


def test_broadcaster_controls_and_snapshot_masking(library):
    async def run():
        immune, modes = [], []
        app = create_app(
            concepts=library.concepts,
            control_token="private-token",
            switch_mode=modes.append,
            set_immune=immune.append,
        )
        async with TestClient(TestServer(app)) as client:
            page = await client.get("/control")
            assert page.status == 200
            assert "private-token" not in await page.text()
            assert (await client.get("/control.js")).status == 200
            assert (await client.post("/api/immune", json={"enabled": True})).status == 403
            headers = {"Authorization": "Bearer private-token"}
            assert (
                await client.post("/api/immune", json={"enabled": "true"}, headers=headers)
            ).status == 400
            assert (
                await client.post("/api/immune", json={"enabled": True}, headers=headers)
            ).status == 202
            assert immune == [True]
            assert (
                await client.post("/api/mode", json={"mode": "telepathy"}, headers=headers)
            ).status == 202
            assert modes == ["telepathy"]
            await app[APP_KEY].publish(
                Mode("telepathy", False, "Make tea.", 0, phase="generating", injection="cats")
            )
            await app[APP_KEY].publish(token())
            await app[APP_KEY].publish(Immune(True))
            state = await (await client.get("/api/state")).json()
            assert state["mode"]["injection"] is None
            assert state["tokens"][0]["applied"] is None
            assert state["immune"]["enabled"]
            async with client.ws_connect("/ws") as ws:
                snapshot = await ws.receive_json()
                assert snapshot["state"]["tokens"][0]["color"] is None
                assert "private-token" not in str(snapshot)

    asyncio.run(run())
