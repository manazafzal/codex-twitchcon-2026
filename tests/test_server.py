import asyncio
import json

from aiohttp import WSCloseCode
from aiohttp.test_utils import TestClient, TestServer

from nous.engine.events import Badge, Mode, Push, Token
from nous.server.app import APP_KEY, create_app
from nous.server.state import ViewState


def test_static_api_auth_and_websocket_broadcast(library, monkeypatch):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")
    async def run():
        switches = []
        app = create_app(
            concepts=library.concepts, control_token="private", switch_mode=switches.append
        )
        async with TestClient(TestServer(app)) as client:
            for path in ["/", "/overlay/", "/fixture.html", "/style.css", "/app.js", "/fixture.js"]:
                response = await client.get(path)
                assert response.status == 200
                assert await response.read()
            assert (await client.get("/SPEC.md")).status == 404
            assert (await client.get("/overlay/../SPEC.md")).status == 404
            assert (await client.post("/api/mode", json={"mode": "attack"})).status == 403
            assert (
                await client.post(
                    "/api/mode", headers={"Authorization": "private"}, json={"mode": "attack"}
                )
            ).status == 403
            headers = {"Authorization": "Bearer private"}
            assert (
                await client.post("/api/mode", headers=headers, json={"mode": "attack"})
            ).status == 202
            assert switches == ["attack"]
            assert (
                await client.post("/api/mode", headers=headers, json={"mode": "bad"})
            ).status == 400
            assert (await client.post("/api/mode", headers=headers, json=[])).status == 400
            first, second = await client.ws_connect("/ws"), await client.ws_connect("/ws")
            assert (await first.receive_json())["kind"] == "snapshot"
            assert (await second.receive_json())["kind"] == "snapshot"
            badge = Badge("SIMULATED ×40", "TINY MODEL / CI")
            await app[APP_KEY].publish(badge)
            assert await first.receive_json() == badge.to_dict()
            assert await second.receive_json() == badge.to_dict()
            state = await (await client.get("/api/state")).json()
            assert state["badge"] == badge.to_dict()
            assert "private" not in json.dumps(state)
            await first.close()
            fresh = await client.ws_connect("/ws")
            assert (await fresh.receive_json())["state"]["badge"] == badge.to_dict()
            await second.close()
            await fresh.close()
        assert app[APP_KEY].closing
        assert app[APP_KEY].task.done()

    asyncio.run(run())


def test_source_task_cancelled_and_ws_closed_on_shutdown():
    async def run():
        ended = asyncio.Event()

        async def source():
            try:
                yield Badge("REPLAY")
                await asyncio.Event().wait()
            finally:
                ended.set()

        app = create_app(source=source)
        client = TestClient(TestServer(app))
        await client.start_server()
        ws = await client.ws_connect("/ws")
        await ws.receive_json()
        closing = asyncio.create_task(ws.receive())
        await client.server.close()
        assert ended.is_set()
        assert (await closing).data == WSCloseCode.GOING_AWAY
        assert ws.close_code in {WSCloseCode.GOING_AWAY, WSCloseCode.OK}
        await client.close()

    asyncio.run(run())


def test_state_history_panels_and_safe_copy():
    state = ViewState()
    for i in range(5):
        state.apply(Mode("war", False, "Tea.", i))
        state.apply(Token(0, str(i), None, {"scores": {}, "top": None, "margin": 0}, None))
        state.apply(Push(f"sim_{i}", "ocean", i, "SIMULATED"))
    assert len(state.data["history"]) == 3
    assert len(state.data["pushes"]) == 5
    snapshot = state.snapshot()
    snapshot.state["tokens"].clear()
    assert state.data["tokens"]
    state.apply(Mode("attack", False, "Tea.", 5, panel="off"))
    state.apply(Token(0, "before", None, {"scores": {}, "top": None, "margin": 0}, None))
    state.apply(Mode("attack", True, "Tea.", 5, panel="on"))
    assert state.data["panels"]["off"][0]["text"] == "before"
