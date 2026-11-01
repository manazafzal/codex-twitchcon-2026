import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp

from thoughtquake.engine.events import Badge, Connection, Event, Round
from thoughtquake.replay.recorder import Recorder
from thoughtquake.server.session import Session
from thoughtquake.twitch.auth import (
    AUTH_BASE,
    HELIX_BASE,
    AuthError,
    OAuth,
    TokenStore,
    TwitchHTTPError,
)
from thoughtquake.twitch.chat_send import ChatSender
from thoughtquake.twitch.eventsub import EVENTSUB_URL, EventSub
from thoughtquake.twitch.parse import ChatParser

log = logging.getLogger(__name__)


class LiveSession:
    def __init__(
        self,
        session: Session,
        client_id: str,
        channel: str,
        *,
        store: TokenStore | None = None,
        record: Path | None = None,
        auth_base: str = AUTH_BASE,
        helix_base: str = HELIX_BASE,
        eventsub_url: str = EVENTSUB_URL,
    ) -> None:
        self.session, self.client_id, self.channel = session, client_id, channel
        self.store = store or TokenStore()
        self.record = record
        self.auth_base, self.helix_base, self.eventsub_url = auth_base, helix_base, eventsub_url
        self.connected = False
        self.output: asyncio.Queue[tuple[Event | Exception, float]] = asyncio.Queue(maxsize=256)
        self.announcements: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        self.last_leader = float("-inf")

    async def emit(self, event: Event) -> None:
        await self.output.put((event, self.session.clock()))

    def announce(self, message: str) -> None:
        if not self.connected:
            return
        try:
            self.announcements.put_nowait(message)
        except asyncio.QueueFull:
            pass

    async def _engine(self) -> None:
        async for event in self.session.events():
            await self.emit(event)
            if isinstance(event, Round):
                self.announce(event.message)

    async def _chat(self) -> None:
        async def status(value: str) -> None:
            self.connected = value == "connected"
            await self.emit(Connection("twitch", value))

        delay = 1.0
        while True:
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=15), trust_env=self.auth_base == AUTH_BASE
                ) as http:
                    auth = OAuth(
                        http,
                        self.client_id,
                        self.store,
                        auth_base=self.auth_base,
                        helix_base=self.helix_base,
                    )
                    token = await auth.validate()
                    users = await auth.request("GET", "/users", params={"login": self.channel})
                    if not users.get("data"):
                        raise ValueError("Twitch channel was not found")
                    broadcaster = users["data"][0]["id"]
                    parser = ChatParser(
                        self.session.library.concepts,
                        bot_id=token.user_id,
                        broadcaster_id=broadcaster,
                        clock=self.session.now,
                    )
                    client = EventSub(
                        auth, broadcaster, token.user_id, url=self.eventsub_url, status=status
                    )
                    sender = ChatSender(auth, broadcaster, token.user_id)

                    async def receive(client: EventSub, parser: ChatParser) -> None:
                        async for notification in client.notifications():
                            push = parser.parse(notification)
                            if push:
                                await self.session.pending.put(push)

                    async def send(sender: ChatSender) -> None:
                        while True:
                            await sender.send(await self.announcements.get())

                    tasks = [
                        asyncio.create_task(receive(client, parser)),
                        asyncio.create_task(auth.maintain()),
                        asyncio.create_task(send(sender)),
                    ]
                    try:
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            task.result()
                        # A terminal revocation ends chat IO but the Subject keeps running.
                        return
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
            except AuthError:
                await status("auth_required")
                log.warning("Twitch login required; run thoughtquake auth again")
                return
            except ValueError:
                await status("channel_unavailable")
                log.warning("Twitch channel was not found; check --channel")
                return
            except (aiohttp.ClientError, OSError, TimeoutError, TwitchHTTPError):
                await status("reconnecting")
                log.warning("Twitch unavailable; continuing the Subject and retrying")
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)

    async def events(self) -> AsyncIterator[Event]:
        recorder = (
            Recorder(self.record, self.session.metadata(), clock=self.session.clock)
            if self.record
            else None
        )
        tasks: list[asyncio.Task[None]] = []

        async def engine() -> None:
            try:
                await self._engine()
            except Exception as exc:
                log.exception("The Subject stopped generating")
                await self.output.put((exc, self.session.clock()))

        try:
            # Publish the source before any incoming chat or connection status.
            badge = Badge(
                "LIVE",
                "TINY MODEL / CI" if self.session.library.config.get("model") == "mock" else None,
                self.session.crowd.users if self.session.crowd.enabled else None,
            )
            if recorder:
                recorder.record(badge)
            yield badge
            initial = Connection("twitch", "reconnecting")
            if recorder:
                recorder.record(initial)
            yield initial
            tasks = [asyncio.create_task(engine()), asyncio.create_task(self._chat())]
            while True:
                event, timestamp = await self.output.get()
                if isinstance(event, Exception):
                    raise event
                if isinstance(event, Badge):
                    continue
                if recorder:
                    recorder.record(event, timestamp=timestamp)
                yield event
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if recorder:
                recorder.close()
