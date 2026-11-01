import asyncio
import logging
import time
from collections.abc import Callable

import aiohttp

from thoughtquake.twitch.auth import AuthError, OAuth, TwitchHTTPError

log = logging.getLogger(__name__)


class ChatSender:
    """Dropping excess announcements avoids queuing stale game commentary."""

    def __init__(
        self,
        auth: OAuth,
        broadcaster_id: str,
        sender_id: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.auth, self.broadcaster_id, self.sender_id = auth, broadcaster_id, sender_id
        self.clock, self.last_sent = clock, float("-inf")
        self.lock = asyncio.Lock()

    async def send(self, text: str) -> bool:
        text = text.strip()[:200]
        if not text:
            return False
        async with self.lock:
            if self.clock() - self.last_sent < 5:
                return False
            self.last_sent = self.clock()
            try:
                body = await self.auth.request(
                    "POST",
                    "/chat/messages",
                    json={
                        "broadcaster_id": self.broadcaster_id,
                        "sender_id": self.sender_id,
                        "message": text,
                    },
                )
                sent = bool(body.get("data") and body["data"][0].get("is_sent"))
                if not sent:
                    log.warning("Twitch dropped a chat announcement")
                return sent
            except (aiohttp.ClientError, TimeoutError, AuthError, TwitchHTTPError):
                log.warning("Twitch chat announcement failed; continuing the game")
                return False
