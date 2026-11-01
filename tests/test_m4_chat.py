import asyncio
import json
from pathlib import Path

import pytest

from thoughtquake.concepts.library import load_concepts
from thoughtquake.engine.events import Control, Guess, Mode, Round, Tick, Token
from thoughtquake.server.session import Session
from thoughtquake.sim.crowd import Crowd
from thoughtquake.twitch.live import LiveSession
from thoughtquake.twitch.parse import ChatParser


def message(text, *, user_id="300", badges=()):
    row = json.loads((Path(__file__).parent / "fixtures/twitch/notification.json").read_text())
    event = row["payload"]["event"]
    event["message_id"] = text
    event["message"]["text"] = text
    event["chatter_user_id"] = user_id
    event["badges"] = [{"set_id": badge} for badge in badges]
    return row


@pytest.mark.parametrize(
    "user,roles,allowed",
    [
        ("300", (), False),
        ("300", ("subscriber",), False),
        ("300", ("moderator",), True),
        ("100", (), True),
        ("200", ("moderator",), True),
    ],
)
def test_only_broadcaster_and_moderators_can_toggle_immune(user, roles, allowed):
    parser = ChatParser(load_concepts(), bot_id="200", broadcaster_id="100")
    result = parser.parse(message("!immune ON", user_id=user, badges=roles))
    assert isinstance(result, Control) is allowed
    if allowed:
        assert result.enabled
    assert parser.parse(message("!war", user_id=user, badges=roles)) is None
    assert parser.parse(message("!telepathy", user_id=user, badges=roles)) is None


def test_guess_command_is_an_input_not_a_faction_push():
    parser = ChatParser(load_concepts(), bot_id="200", broadcaster_id="100", clock=lambda: 4)
    result = parser.parse(message("!guess sea"))
    assert isinstance(result, Guess) and result.word == "sea" and result.t == 4
    assert parser.parse(message("!guess sea", user_id="200")) is None
    assert parser.parse(message("!immune maybe", badges=("moderator",))) is None


def test_live_chat_announcements_only_come_from_round_boundaries():
    async def run():
        session = Session(crowd=Crowd(twitch_connected=True), source="LIVE")

        async def events():
            yield Mode("war", False, "Make tea.", 0)
            yield Tick({"ocean": 0.75, "Neutral": 0.25}, 1, [], 60)
            yield Token(31, "tea.", "ocean", {"scores": {}, "top": None, "margin": 0}, "ocean")
            yield Round("war", "start", 0, "Start round.")
            yield Round("war", "end", 0, "End round.")
            yield Round("telepathy", "reveal", 1, "Reveal round.")

        session.events = events
        live = LiveSession(session, "test-client", "streamer")
        notices = []
        live.announce = notices.append
        await live._engine()
        assert notices == ["Start round.", "End round.", "Reveal round."]

    asyncio.run(run())
