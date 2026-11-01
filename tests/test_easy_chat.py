import asyncio

import pytest

from nous.concepts.library import load_concepts
from nous.engine.commands import Participation, StartRound
from nous.engine.events import Control, Guess, Push
from nous.engine.mixer import FakeClock, Mixer
from nous.server.scoring import Scoring
from nous.server.session import Session
from nous.sim.crowd import Crowd
from nous.twitch.live import LiveSession
from nous.twitch.parse import ChatParser
from nous.twitch.welcome import Welcomes


def notification(text, *, user="42", name="Friend", badges=(), message_id=None):
    return {
        "metadata": {"message_type": "notification"},
        "payload": {
            "subscription": {"type": "channel.chat.message", "version": "1"},
            "event": {
                "broadcaster_user_id": "channel",
                "chatter_user_id": user,
                "chatter_user_name": name,
                "message_id": message_id or f"{user}:{text}",
                "badges": [{"set_id": role} for role in badges],
                "message": {"text": text},
            },
        },
    }


def parser(clock=None):
    return ChatParser(
        load_concepts(), bot_id="bot", broadcaster_id="channel", clock=clock or FakeClock()
    )


def test_join_balances_teams_pushes_are_deliberate_and_plain_words_are_light():
    p = parser()
    assert [p.parse(notification("!join", user=str(i))).faction for i in range(3)] == [
        "ocean",
        "space",
        "jazz",
    ]
    assert p.passive
    joined = p.parse(notification("!join", user="0", message_id="again"))
    assert joined.faction == "ocean"
    push = p.parse(notification("!push sea"))
    assert isinstance(push, Push) and push.faction == "ocean" and not p.passive
    assert p.parse(notification("What a lovely wave!")).faction == "ocean" and p.passive
    assert p.parse(notification("Nice! 🚀!")).faction == "space" and p.passive
    assert p.parse(notification("OceanWave")).faction == "ocean" and p.passive
    assert p.parse(notification("Love this🦖!")).faction == "romance" and p.passive
    assert p.parse(notification("Nice🦖!")).faction == "dinosaurs" and p.passive
    assert p.parse(notification("🍕")).faction == "pizza" and p.passive
    assert isinstance(p.parse(notification("!guess sea")), Guess)
    assert not p.passive
    assert p.parse(notification("!join", user="bot")) is None
    host = ChatParser(load_concepts(), bot_id="channel", broadcaster_id="channel")
    assert isinstance(host.parse(notification("!join", user="channel")), Push)
    assert host.parse(notification("Team Ocean! Try !push ocean.", user="channel")) is None


@pytest.mark.parametrize(
    "roles,allowed",
    [((), False), (("subscriber",), False), (("moderator",), True), (("broadcaster",), True)],
)
def test_round_requires_a_streamer_or_mod(roles, allowed):
    p = parser()
    assert isinstance(p.parse(notification("!round", badges=roles)), StartRound) == allowed
    assert isinstance(p.parse(notification("!round", user="channel")), StartRound)
    immune = p.parse(notification("!immune", user="channel"))
    assert isinstance(immune, Control) and immune.enabled
    assert p.parse(notification("!war", badges=roles)) is None


def test_passive_chat_does_not_use_push_allowance_or_outscore_a_push():
    clock = FakeClock()
    mixer, score = Mixer(clock=clock), Scoring(clock=clock)
    for i in range(1000):
        event = Push("Lurker", "ocean", clock(), "LIVE", "lurker")
        weight = mixer.push(event, passive=True)
        score.push("lurker", "Lurker", "ocean", weight, passive=True)
    assert mixer.push(Push("Pusher", "ocean", clock(), "LIVE", "pusher")) == 1
    score.push("pusher", "Pusher", "ocean", 1)
    score.finish({"ocean": 1})
    assert score.board.stream["lurker"]["points"] == pytest.approx(20 * 0.1 / 1.1)
    assert score.board.stream["pusher"]["points"] == pytest.approx(20 / 1.1)
    # A passive word cannot consume this same viewer's first full push.
    assert mixer.push(Push("Lurker", "ocean", clock(), "LIVE", "lurker")) == 1
    clock.advance(20)
    assert mixer.push(Push("Lurker", "ocean", clock(), "LIVE", "lurker"), passive=True) == 0.1


def test_welcomes_once_per_viewer_varied_bounded_and_hidden_when_blind():
    clock = FakeClock()
    welcomes = Welcomes(load_concepts(), clock=clock)
    welcomes.offer("1", "Ada", "ocean")
    welcomes.offer("1", "Ada renamed", "space")
    first = welcomes.take(blind=False)
    assert "Ada" in first and "!push ocean" in first
    welcomes.offer("2", "Sea", "ocean")
    assert welcomes.take(blind=True) is None
    clock.advance(10)
    second = welcomes.take(blind=True)
    assert (
        "!guess <word>" in second and "sea" not in second.lower() and "ocean" not in second.lower()
    )
    assert first.split()[0] != second.split()[0]
    assert welcomes.take(blind=False) is None
    for i in range(1000):
        welcomes.offer(str(i + 10), "Visitor", "jazz")
    assert len(welcomes.pending) == 8


def test_live_receive_wraps_light_input_welcomes_first_contribution_and_waits_for_sender():
    async def run():
        clock = FakeClock()
        session = Session(clock=clock, crowd=Crowd(twitch_connected=True))
        live = LiveSession(session, "public-code", "channel")
        p = parser(clock)
        await live.receive_chat(p, notification("!join", name="Ada"))
        command = session.pending.get_nowait()
        assert isinstance(command, Participation) and command.passive
        await live.receive_chat(p, notification("!push sea", name="Ada"))
        assert isinstance(session.pending.get_nowait(), Push)
        assert len(live.welcomes.pending) == 1

        class Sender:
            def __init__(self):
                self.last_sent = clock()
                self.messages = []

            def clock(self):
                return clock()

            async def send(self, message):
                self.messages.append(message)
                self.last_sent = clock()
                return True

        sender = Sender()
        assert not await live.send_welcome(sender)
        clock.advance(5)
        assert await live.send_welcome(sender)
        assert len(sender.messages) == 1 and "Ada" in sender.messages[0]
        clock.advance(20)
        assert not await live.send_welcome(sender)
        session.start_round()
        session.drain()
        assert session.mode == "telepathy"

    asyncio.run(run())
