import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import aiohttp

from nous.twitch.auth import AuthError, OAuth, TwitchHTTPError

log = logging.getLogger(__name__)
EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"


class Revoked(RuntimeError):
    pass


class EventSub:
    def __init__(
        self,
        auth: OAuth,
        broadcaster_id: str,
        user_id: str,
        *,
        url: str = EVENTSUB_URL,
        welcome_timeout: float = 10,
        keepalive_grace: float = 5,
        backoff_max: float = 60,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        status: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.auth, self.broadcaster_id, self.user_id = auth, broadcaster_id, user_id
        self.url, self.welcome_timeout = url, welcome_timeout
        self.keepalive_grace, self.backoff_max = keepalive_grace, backoff_max
        self.sleep, self.status = sleep, status
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.healthy = False

    async def _status(self, value: str) -> None:
        if self.status:
            await self.status(value)

    async def _subscribe(self, session_id: str) -> None:
        async with asyncio.timeout(min(10, self.welcome_timeout)):
            await self.auth.request(
                "POST",
                "/eventsub/subscriptions",
                json={
                    "type": "channel.chat.message",
                    "version": "1",
                    "condition": {
                        "broadcaster_user_id": self.broadcaster_id,
                        "user_id": self.user_id,
                    },
                    "transport": {"method": "websocket", "session_id": session_id},
                },
            )

    async def _connection(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[tuple[aiohttp.ClientWebSocketResponse, dict[str, Any] | Exception]] = (
            asyncio.Queue(maxsize=1024)
        )
        readers: dict[aiohttp.ClientWebSocketResponse, asyncio.Task[None]] = {}
        sockets: list[aiohttp.ClientWebSocketResponse] = []

        async def read(ws: aiohttp.ClientWebSocketResponse) -> None:
            timeout = self.welcome_timeout
            try:
                while True:
                    # aiohttp handles ping/pong without resetting this text-frame deadline.
                    async with asyncio.timeout(timeout):
                        frame = await ws.receive()
                    if frame.type != aiohttp.WSMsgType.TEXT:
                        raise ConnectionError("EventSub socket closed")
                    data = frame.json()
                    if not isinstance(data, dict):
                        raise TypeError("Invalid EventSub frame")
                    kind = data.get("metadata", {}).get("message_type")
                    if kind == "session_welcome":
                        interval = data["payload"]["session"].get("keepalive_timeout_seconds") or 30
                        timeout = float(interval) + self.keepalive_grace
                    await queue.put((ws, data))
            except (
                aiohttp.ClientError,
                OSError,
                TimeoutError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                await queue.put((ws, exc))

        async def open_socket(url: str) -> aiohttp.ClientWebSocketResponse:
            async with asyncio.timeout(self.welcome_timeout):
                ws = await self.auth.http.ws_connect(url, autoping=True, heartbeat=None)
            sockets.append(ws)
            readers[ws] = asyncio.create_task(read(ws))
            return ws

        current = None
        migrating = None
        welcomed = False
        try:
            current = await open_socket(self.url)
            while True:
                ws, data = await queue.get()
                if isinstance(data, Exception):
                    if ws is current or ws is migrating:
                        raise data
                    continue
                kind = data.get("metadata", {}).get("message_type")
                if kind == "session_welcome":
                    if ws is migrating:
                        old, current = current, ws
                        migrating = None
                        # New welcome confirms the transfer; never resubscribe this path.
                        await old.close()
                        readers[old].cancel()
                    elif ws is current and not welcomed:
                        await self._subscribe(data["payload"]["session"]["id"])
                        welcomed = True
                    await self._status("connected")
                elif not welcomed:
                    raise ValueError("EventSub message arrived before welcome")
                elif kind == "session_reconnect" and ws is current and migrating is None:
                    await self._status("reconnecting")
                    # The old reader stays active while the replacement is established.
                    migrating = await open_socket(data["payload"]["session"]["reconnect_url"])
                elif kind == "session_keepalive":
                    self.healthy = True
                elif kind == "notification":
                    self.healthy = True
                    message_id = data.get("metadata", {}).get("message_id")
                    if message_id and message_id not in self.seen:
                        self.seen[message_id] = None
                        if len(self.seen) > 4096:
                            self.seen.popitem(last=False)
                        yield data
                elif kind == "revocation":
                    await self._status("revoked")
                    raise Revoked("Twitch revoked the chat subscription; check authorization")
        finally:
            for task in readers.values():
                task.cancel()
            await asyncio.gather(*readers.values(), return_exceptions=True)
            await asyncio.gather(*(ws.close() for ws in sockets), return_exceptions=True)

    async def notifications(self) -> AsyncIterator[dict[str, Any]]:
        delay = 1.0
        while True:
            self.healthy = False
            try:
                connection = self._connection()
                try:
                    async for message in connection:
                        yield message
                finally:
                    await connection.aclose()
            except Revoked:
                log.warning("Twitch revoked the chat subscription; run nous auth again")
                return
            except AuthError:
                await self._status("auth_required")
                log.warning("Twitch authentication failed; run nous auth again")
                return
            except (
                aiohttp.ClientError,
                OSError,
                TimeoutError,
                ValueError,
                TypeError,
                KeyError,
                TwitchHTTPError,
            ):
                log.warning("EventSub connection interrupted; reconnecting")
                await self._status("reconnecting")
            if self.healthy:
                delay = 1.0
            await self.sleep(delay)
            delay = min(delay * 2, self.backoff_max)
