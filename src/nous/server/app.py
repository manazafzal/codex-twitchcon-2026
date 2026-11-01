import asyncio
import contextlib
import ipaddress
import logging
import os
import secrets
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from typing import Any

from aiohttp import WSMsgType, web

from nous.concepts.library import Concept, load_concepts
from nous.engine.events import Event, Mode, Round, Tick
from nous.server.leaderboard import Leaderboard
from nous.server.presentation import Presentation
from nous.server.state import ViewState

log = logging.getLogger(__name__)
APP_KEY = web.AppKey("nous_server", object)


class Server:
    def __init__(
        self,
        *,
        concepts: list[Concept] | None = None,
        control_token: str | None = None,
        switch_mode: Callable[[str], None] | None = None,
        set_immune: Callable[[bool], None] | None = None,
        leaderboard: Leaderboard | None = None,
        start_round: Callable[[], None] | None = None,
    ) -> None:
        self.start_round = start_round
        self.state = ViewState(concepts)
        self.leaderboard = leaderboard
        self.control_token = control_token or secrets.token_urlsafe(32)
        self.switch_mode, self.set_immune = switch_mode, set_immune
        self.presentation = Presentation(concepts or load_concepts())
        self.clients: dict[web.WebSocketResponse, asyncio.Queue[dict[str, Any]]] = {}
        self.task: asyncio.Task[None] | None = None
        self.closing = False
        self.last_tick: Tick | None = None

    async def publish(self, event: Event) -> None:
        if isinstance(event, Round) and event.phase == "catalog":
            import json

            payload = json.loads(event.message)
            concepts = [
                Concept(**{**c, "aliases": tuple(c["aliases"])}) for c in payload["concepts"]
            ]
            await self.update_catalog(concepts)
        if isinstance(event, Tick):
            self.last_tick = event
        if isinstance(event, Mode) and event.phase in {"guessing", "reveal", "idle"}:
            tail = self.presentation.finish_token()
            if tail:
                await self.broadcast(tail)
        event = self.presentation.event(event)
        if isinstance(event, Mode) and event.phase == "reveal" and self.leaderboard:
            from dataclasses import replace

            event = replace(
                event,
                scoreboard=tuple(
                    (row["name"], int(row["points"]))
                    for row in self.leaderboard.top(self.leaderboard.stream)
                ),
            )
        await self.broadcast(event)
        if isinstance(event, Mode) and self.presentation.points:
            await self.broadcast(self.presentation.layout())
            if event.phase == "reveal":
                if self.last_tick is not None:
                    await self.broadcast(self.last_tick)
                await self.broadcast(self.state.snapshot())

    async def update_catalog(self, concepts: list[Concept]) -> None:
        if self.presentation.blind:
            raise RuntimeError("Catalog publication must wait for a visible boundary")
        previous = self.state.data
        self.state = ViewState(concepts)
        for key in ("badge", "connections", "immune", "immune_requested", "mode"):
            self.state.data[key] = previous[key]
        self.presentation = Presentation(concepts)
        await self.broadcast(self.state.snapshot())

    async def broadcast(self, event: Event) -> None:
        self.state.apply(event)
        row = event.to_dict()
        slow = []
        for ws, queue in list(self.clients.items()):
            try:
                queue.put_nowait(row)
            except asyncio.QueueFull:
                self.clients.pop(ws, None)
                slow.append(ws.close(code=1013, message=b"Reconnect for a fresh snapshot"))
        if slow:
            await asyncio.gather(*slow, return_exceptions=True)

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        await ws.prepare(request)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        # No await between capturing the snapshot and subscribing to subsequent frames.
        snapshot = self.state.snapshot()
        if self.presentation.strict:
            snapshot = self.presentation.strict.event(snapshot)
        queue.put_nowait(snapshot.to_dict())
        self.clients[ws] = queue

        async def writer() -> None:
            while True:
                await ws.send_json(await queue.get())

        task = asyncio.create_task(writer())
        try:
            async for message in ws:
                if message.type == WSMsgType.ERROR:
                    log.debug("Overlay socket closed: %s", ws.exception())
        finally:
            self.clients.pop(ws, None)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                await task
        return ws

    async def api_state(self, request: web.Request) -> web.Response:
        snapshot = self.state.snapshot()
        if self.presentation.strict:
            snapshot = self.presentation.strict.event(snapshot)
        return web.json_response(snapshot.state)

    async def api_leaderboard(self, request: web.Request) -> web.Response:
        import hashlib

        data = (self.leaderboard or Leaderboard()).snapshot(blind=self.presentation.blind)
        if self.presentation.blind and self.presentation.strict:
            for key in ("stream", "all_time"):
                for row in data[key]:
                    row["name"] = self.presentation.strict.clean(row["name"])
                    row["id"] = hashlib.sha256(row["id"].encode()).hexdigest()[:16]
        return web.json_response(data)

    def authorize(self, request: web.Request) -> None:
        try:
            local = ipaddress.ip_address(request.remote or "").is_loopback
        except ValueError:
            local = False
        auth = request.headers.get("Authorization", "")
        supplied = (
            auth[7:] if auth.startswith("Bearer ") else request.cookies.get("nous_control", "")
        )
        if not auth.startswith("Bearer "):
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                raise web.HTTPForbidden(text="Open this page directly in NOUS.")
            if (
                request.method not in {"GET", "HEAD"}
                and request.headers.get("Origin") != f"{request.scheme}://{request.host}"
            ):
                raise web.HTTPForbidden(text="Use the controls in your NOUS window.")
        if not local or not secrets.compare_digest(supplied, self.control_token):
            raise web.HTTPForbidden(text="Local broadcaster token required")

    async def api_mode(self, request: web.Request) -> web.Response:
        self.authorize(request)
        try:
            body = await request.json()
            mode = body["mode"].lower()
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise web.HTTPBadRequest(text="Expected a mode object") from exc
        if mode not in {"war", "attack", "telepathy"}:
            raise web.HTTPBadRequest(text="Unknown mode")
        if self.switch_mode is None:
            raise web.HTTPConflict(text="Mode changes unavailable during frame replay")
        self.switch_mode(mode)
        return web.json_response({"mode": mode, "status": "queued"}, status=202)

    async def api_immune(self, request: web.Request) -> web.Response:
        self.authorize(request)
        try:
            body = await request.json()
            enabled = body["enabled"]
            if not isinstance(enabled, bool):
                raise TypeError("Expected boolean")
        except (ValueError, KeyError, TypeError) as exc:
            raise web.HTTPBadRequest(text="Expected an enabled boolean") from exc
        if self.set_immune is None:
            raise web.HTTPConflict(text="Immune controls unavailable during replay")
        self.set_immune(enabled)
        return web.json_response({"enabled": enabled, "status": "queued"}, status=202)

    async def api_round(self, request: web.Request) -> web.Response:
        self.authorize(request)
        if self.start_round is None:
            raise web.HTTPConflict(text="Open a demo or live game first.")
        self.start_round()
        return web.json_response({"status": "queued"}, status=202)


def create_app(
    *,
    source: Callable[[], AsyncIterator[Event]] | None = None,
    concepts: list[Concept] | None = None,
    control_token: str | None = None,
    switch_mode: Callable[[str], None] | None = None,
    set_immune: Callable[[bool], None] | None = None,
    leaderboard: Leaderboard | None = None,
    start_round: Callable[[], None] | None = None,
    welcome_home: bool = False,
) -> web.Application:
    server = Server(
        concepts=concepts,
        control_token=control_token,
        switch_mode=switch_mode,
        set_immune=set_immune,
        leaderboard=leaderboard,
        start_round=start_round,
    )
    app = web.Application(client_max_size=4096)
    app[APP_KEY] = server
    app.router.add_get("/ws", server.websocket)
    app.router.add_get("/api/state", server.api_state)
    app.router.add_get("/api/leaderboard", server.api_leaderboard)
    app.router.add_post("/api/mode", server.api_mode)
    app.router.add_post("/api/immune", server.api_immune)
    app.router.add_post("/api/round", server.api_round)
    overlay = files("nous.overlay")

    async def asset(request: web.Request) -> web.StreamResponse:
        name = (
            "welcome.html"
            if welcome_home and request.path == "/"
            else "control.html"
            if request.path == "/control"
            else request.match_info.get("name") or "index.html"
        )
        if (
            name in {"fixture.html", "fixture.js", "trace_data.js"}
            and os.getenv("NOUS_DEV_FIXTURES") != "1"
        ):
            raise web.HTTPNotFound()
        if name not in {
            "index.html",
            "fixture.html",
            "style.css",
            "app.js",
            "atlas.js",
            "trace_data.js",
            "fixture.js",
            "control.html",
            "control.js",
            "welcome.html",
            "welcome.js",
            "welcome.css",
        }:
            raise web.HTTPNotFound()
        return web.FileResponse(str(overlay.joinpath(name)))

    async def font(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        if name not in {
            "CormorantGaramond.ttf",
            "IBMPlexMono.ttf",
            "OFL-Cormorant.txt",
            "OFL-IBMPlex.txt",
        }:
            raise web.HTTPNotFound()
        return web.FileResponse(str(overlay.joinpath("fonts", name)))

    app.router.add_get("/fonts/{name}", font)
    app.router.add_get("/overlay/fonts/{name}", font)
    app.router.add_get("/control", asset)
    app.router.add_get("/", asset)
    app.router.add_get("/overlay/", asset)
    app.router.add_get("/overlay/{name}", asset)
    app.router.add_get("/{name}", asset)

    async def lifecycle(application: web.Application) -> AsyncIterator[None]:
        async def produce() -> None:
            delay = 0.5
            while source:
                try:
                    async for event in source():
                        await server.publish(event)
                        if event.kind == "token":
                            delay = 0.5
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - supervise arbitrary backend failures without private text
                    from nous.engine.events import Connection

                    log.error("Producer failed; restarting the Subject")
                    await server.publish(Connection("engine", "error"))
                    await asyncio.sleep(delay)
                    delay = min(10, delay * 2)

        server.task = asyncio.create_task(produce())
        yield
        server.closing = True
        server.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server.task
        await asyncio.gather(
            *(ws.close(code=1001, message=b"Server shutdown") for ws in list(server.clients)),
            return_exceptions=True,
        )

    async def close_sockets(application: web.Application) -> None:
        await asyncio.gather(
            *(ws.close(code=1001, message=b"Server shutdown") for ws in list(server.clients)),
            return_exceptions=True,
        )

    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(close_sockets)
    return app
