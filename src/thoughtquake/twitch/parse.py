import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from thoughtquake.concepts.library import Concept, match_concept
from thoughtquake.engine.events import Push


class ChatParser:
    def __init__(
        self,
        concepts: list[Concept],
        *,
        bot_id: str,
        broadcaster_id: str,
        clock: Callable[[], float] = time.monotonic,
        dedupe_size: int = 4096,
    ) -> None:
        self.concepts, self.bot_id, self.broadcaster_id = concepts, bot_id, broadcaster_id
        self.clock, self.dedupe_size = clock, dedupe_size
        self.seen: OrderedDict[str, None] = OrderedDict()

    def parse(self, message: dict[str, Any]) -> Push | None:
        if message.get("metadata", {}).get("message_type") != "notification":
            return None
        payload = message.get("payload", {})
        subscription = payload.get("subscription", {})
        if subscription.get("type") != "channel.chat.message" or subscription.get("version") != "1":
            return None
        event = payload.get("event", {})
        if event.get("broadcaster_user_id") != self.broadcaster_id:
            return None
        user_id = event.get("chatter_user_id")
        if not user_id or user_id == self.bot_id:
            return None
        message_id = event.get("message_id")
        if not message_id or message_id in self.seen:
            return None
        self.seen[message_id] = None
        if len(self.seen) > self.dedupe_size:
            self.seen.popitem(last=False)
        text = event.get("message", {}).get("text", "")
        if not isinstance(text, str):
            return None
        faction = match_concept(text, self.concepts)
        if faction is None:
            return None
        name = event.get("chatter_user_name") or event.get("chatter_user_login") or user_id
        return Push(name, faction, self.clock(), "LIVE", user_id=user_id)
