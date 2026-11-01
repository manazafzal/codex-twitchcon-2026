import asyncio
import contextlib
import ipaddress
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from importlib.resources import files
from typing import Any

from aiohttp import WSMsgType, web

from thoughtquake.concepts.library import Concept
from thoughtquake.engine.events import Event
from thoughtquake.server.state import ViewState

log = logging.getLogger(__name__)
APP_KEY = web.AppKey("thoughtquake_server", object)


class Server:
    def __init__(
        self,
        *,
        concepts: list[Concept] | None = None,
        control_token: str | None = None,
        switch_mode: Callable[[str], None] | None = None,
    ) -> None:
        self.state = ViewState(concepts)
        self.control_token = control_token or secrets.token_urlsafe(32)
        self.switch_mode = switch_mode
        self.clients: dict[web.WebSocketResponse, asyncio.Queue[dict[str, Any]]] = {}
        self.task: asyncio.Task[None] | None = None
        self.closing = False

    async def publish(self, event: Event) -> None:
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
        queue.put_nowait(self.state.snapshot().to_dict())
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
        return web.json_response(self.state.snapshot().state)

    async def api_mode(self, request: web.Request) -> web.Response:
        try:
            local = ipaddress.ip_address(request.remote or "").is_loopback
        except ValueError:
            local = False
        auth = request.headers.get("Authorization", "")
        supplied = auth[7:] if auth.startswith("Bearer ") else ""
        if not local or not secrets.compare_digest(supplied, self.control_token):
            raise web.HTTPForbidden(text="Local broadcaster token required")
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


def create_app(
    *,
    source: Callable[[], AsyncIterator[Event]] | None = None,
    concepts: list[Concept] | None = None,
    control_token: str | None = None,
    switch_mode: Callable[[str], None] | None = None,
) -> web.Application:
    server = Server(concepts=concepts, control_token=control_token, switch_mode=switch_mode)
    app = web.Application(client_max_size=4096)
    app[APP_KEY] = server
    app.router.add_get("/ws", server.websocket)
    app.router.add_get("/api/state", server.api_state)
    app.router.add_post("/api/mode", server.api_mode)
    overlay = files("thoughtquake.overlay")

    async def asset(request: web.Request) -> web.StreamResponse:
        name = request.match_info.get("name") or "index.html"
        if name not in {"index.html", "fixture.html", "style.css", "app.js", "fixture.js"}:
            raise web.HTTPNotFound()
        return web.FileResponse(str(overlay.joinpath(name)))

    app.router.add_get("/", asset)
    app.router.add_get("/overlay/", asset)
    app.router.add_get("/overlay/{name}", asset)
    app.router.add_get("/{name}", asset)

    async def lifecycle(application: web.Application) -> AsyncIterator[None]:
        async def produce() -> None:
            if source:
                async for event in source():
                    await server.publish(event)

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
