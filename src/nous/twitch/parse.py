import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from nous.concepts.library import Concept, match_concept
from nous.engine.commands import Rank, StartRound
from nous.engine.events import Control, Guess, Push

TEAM_EMOTES = {
    "🌊": "ocean",
    "🚀": "space",
    "🎷": "jazz",
    "👻": "horror",
    "🌱": "gardening",
    "⚔️": "war",
    "🏴‍☠️": "pirates",
    "🦖": "dinosaurs",
    "🧪": "chemistry",
    "⚽": "football",
    "🤖": "robots",
    "🪄": "wizards",
    "🔍": "detective",
    "🐱": "cats",
    "🐉": "dragons",
    "🏰": "medieval",
    "💘": "romance",
    "🥷": "ninjas",
    "🌋": "volcano",
    "🏜️": "desert",
    "❄️": "winter",
    "🎪": "circus",
    "🚜": "farm",
    "🪩": "disco",
    "⛈️": "weather",
    "📚": "library",
    "🏫": "school",
    "🍕": "pizza",
    "⏳": "time-travel",
    "🍳": "cooking",
    "oceanwave": "ocean",
    "spacerocket": "space",
    "jazzsax": "jazz",
}


class ChatParser:
    def __init__(
        self,
        concepts: list[Concept],
        *,
        bot_id: str,
        broadcaster_id: str,
        clock: Callable[[], float] = time.monotonic,
        dedupe_size: int = 4096,
        teams: dict[str, str] | None = None,
    ) -> None:
        self.concepts, self.bot_id, self.broadcaster_id = concepts, bot_id, broadcaster_id
        self.clock, self.dedupe_size = clock, dedupe_size
        self.known = {c.id for c in concepts}
        self.teams = teams if teams is not None else {}
        self.passive = False
        self.participant: tuple[str, str, str] | None = None
        self.seen: OrderedDict[str, None] = OrderedDict()

    def parse(self, message: dict[str, Any]) -> Push | Guess | Control | Rank | StartRound | None:
        self.passive = False
        self.participant = None
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
        if not user_id:
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
        name = event.get("chatter_user_name") or event.get("chatter_user_login") or user_id
        words = text.strip().split(maxsplit=1)
        command = words[0].casefold() if words else ""
        argument = words[1].strip() if len(words) > 1 else ""
        if command == "!immune":
            roles = {badge.get("set_id") for badge in (event.get("badges") or [])}
            authorized = user_id == self.broadcaster_id or bool(
                roles & {"broadcaster", "moderator"}
            )
            if authorized and argument.casefold() in {"", "on", "off"}:
                return Control(argument.casefold() != "off", self.clock(), "LIVE", name, user_id)
            return None
        if command == "!round":
            roles = {badge.get("set_id") for badge in (event.get("badges") or [])}
            if user_id == self.broadcaster_id or roles & {"broadcaster", "moderator"}:
                return StartRound(name, user_id, "LIVE")
            return None
        if user_id == self.bot_id and (
            user_id != self.broadcaster_id or command not in {"!join", "!push", "!guess", "!rank"}
        ):
            return None
        if command == "!rank":
            return Rank(name, user_id)
        if command == "!guess":
            if argument:
                self.participant = (user_id, name, self.teams.get(user_id, ""))
            return Guess(name, argument, self.clock(), "LIVE", user_id) if argument else None
        if command == "!join":
            choices = [c.id for c in self.concepts[:3]]
            faction = self.teams.setdefault(user_id, choices[len(self.teams) % len(choices)])
            self.passive = True
            self.participant = (user_id, name, faction)
            return Push(name, faction, self.clock(), "LIVE", user_id=user_id)
        if command.startswith("!") and command != "!push":
            return None
        faction = match_concept(argument if command == "!push" else text, self.concepts)
        if faction is None:
            faction = next(
                (
                    idea
                    for emote, idea in TEAM_EMOTES.items()
                    if not emote.isascii() and emote in text
                ),
                None,
            )
        if faction is None:
            for word in text.split():
                if word.strip("!?.,;()").casefold() in TEAM_EMOTES:
                    faction = TEAM_EMOTES[word.strip("!?.,;()").casefold()]
                    break
        if faction not in self.known:
            return None
        self.passive = command != "!push"
        self.teams[user_id] = faction
        self.participant = (user_id, name, faction)
        return Push(name, faction, self.clock(), "LIVE", user_id=user_id)
