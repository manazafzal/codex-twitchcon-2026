import asyncio
import json

import numpy as np

from nous.engine.commands import Rank
from nous.engine.events import Control, Guess, Mode, Push, Round, Tamper, Token
from nous.engine.mixer import FakeClock
from nous.server.session import Session
from nous.sim.crowd import Crowd
from nous.twitch.live import LiveSession
from nous.twitch.parse import ChatParser


def session_with_clock():
    clock = FakeClock()
    return Session(clock=clock, crowd=Crowd(twitch_connected=True)), clock


def open_guesses(session):
    session.begin_round()
    secret = session.telepathy.arm(set())
    session.telepathy.start()
    session.telepathy.finish_generation({secret: 1})
    return secret


def test_queued_correct_guesses_receive_decreasing_awards_before_finalising():
    session, clock = session_with_clock()
    secret = open_guesses(session)
    for i in range(6):
        session.pending.put_nowait(Guess(f"Viewer {i}", secret, clock(), "LIVE", str(i)))
    events = session.drain()
    assert [session.scoring.board.stream[str(i)]["points"] for i in range(6)] == [
        100,
        60,
        40,
        25,
        15,
        10,
    ]
    assert session.telepathy.winner == "Viewer 0"
    assert session.telepathy.scoreboard == (("Viewer 0", 1),)
    assert sum(isinstance(e, Round) and e.phase == "mvp" for e in events) == 1
    assert not session.reveal_events()
    session.pending.put_nowait(Guess("Late", secret, clock(), "LIVE", "late"))
    session.drain()
    assert "late" not in session.scoring.board.stream


def test_guess_spam_limit_applies_to_round_win_as_well_as_points():
    session, clock = session_with_clock()
    secret = open_guesses(session)
    for at in (0, 2, 4):
        session.pending.put_nowait(Guess("Spam", "ordinary", at, "LIVE", "spam"))
    clock.advance(6)
    session.pending.put_nowait(Guess("Spam renamed", secret, 6, "LIVE", "spam"))
    session.pending.put_nowait(Guess("Careful", secret, 6, "LIVE", "careful"))
    session.drain()
    assert session.telepathy.winner == "Careful"
    assert "spam" not in session.scoring.board.stream
    assert session.scoring.board.stream["careful"]["points"] == 100


def test_guess_cooldown_rejects_a_fast_second_attempt_in_director():
    session, clock = session_with_clock()
    secret = open_guesses(session)
    session.pending.put_nowait(Guess("Viewer", "ordinary", 0, "LIVE", "viewer"))
    session.pending.put_nowait(Guess("Viewer", secret, 0.1, "LIVE", "viewer"))
    clock.advance(0.1)
    session.drain()
    assert session.telepathy.winner is None
    assert not session.scoring.board.stream
    clock.advance(1.9)
    session.pending.put_nowait(Guess("Viewer", secret, clock(), "LIVE", "viewer"))
    session.drain()
    assert session.telepathy.winner == "Viewer"


def install_short_answers(session, monkeypatch, *, applied="ocean", alarm=False):
    real_sleep = asyncio.sleep

    async def sleep(_):
        await real_sleep(0)

    async def stream(*, max_tokens):
        index = session.engine.answer_index
        session.engine.answer_index += 1
        session.engine.mixer.select(0, np.random.default_rng(0))
        yield Mode("war", session.engine.immune, "Make tea.", index)
        for i, text in enumerate(("A quiet ", "tide.")):
            yield Token(i, text, applied, {"scores": {}, "top": None, "margin": 0}, applied)
        if alarm and session.engine.immune:
            yield Tamper(("ocean",), 0.8)
        session.engine.last_text = "A quiet tide."
        session.engine.last_exempt = set()

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(session.engine, "stream", stream)


def test_attack_finishes_once_after_both_panels_and_rewards_live_mod_catch(monkeypatch):
    async def run():
        session, clock = session_with_clock()
        install_short_answers(session, monkeypatch, alarm=True)
        session.begin_round()
        session.pending.put_nowait(Push("A", "ocean", clock(), "LIVE", "a"))
        session.pending.put_nowait(Push("B", "ocean", clock(), "LIVE", "b"))
        session.pending.put_nowait(Control(True, clock(), "LIVE", "Mod", "mod"))
        session.drain()
        events = [event async for event in session._attack()]
        on = next(i for i, e in enumerate(events) if isinstance(e, Mode) and e.panel == "on")
        mvp = [i for i, e in enumerate(events) if isinstance(e, Round) and e.phase == "mvp"]
        assert len(mvp) == 1 and mvp[0] > on
        assert session.scoring.board.stream["a"]["points"] == 10
        assert session.scoring.board.stream["b"]["points"] == 10
        assert session.scoring.board.stream["mod"]["points"] == 15
        assert json.loads(events[mvp[0]].message)["mvp"]["id"] == "mod"
        session.begin_round()
        assert session.controller is None
        session.pending.put_nowait(Control(True, clock(), "LOCAL"))
        session.drain()
        assert session.controller is None

    asyncio.run(run())


def test_late_answer_pushes_receive_next_round_credit_not_current_credit(monkeypatch):
    async def run():
        session, clock = session_with_clock()
        install_short_answers(session, monkeypatch)
        session.begin_round()
        session.pending.put_nowait(Push("Early", "ocean", clock(), "LIVE", "early"))
        session.drain()
        async for event in session._answer("war"):
            if isinstance(event, Token) and event.i == 0:
                session.pending.put_nowait(Push("Late", "ocean", clock(), "LIVE", "late"))
        assert session.scoring.board.stream["early"]["points"] == 20
        assert "late" not in session.scoring.board.stream
        assert len(session.pending_points) == 1
        session.begin_round()
        assert not session.pending_points
        _ = [e async for e in session._answer("war")]
        assert session.scoring.board.stream["late"]["points"] == 20
        assert session.scoring.board.stream["early"]["points"] == 20

    asyncio.run(run())


def test_incidental_neutral_word_earns_no_push_points(monkeypatch):
    async def run():
        session, clock = session_with_clock()
        install_short_answers(session, monkeypatch, applied=None)
        session.begin_round()
        session.pending.put_nowait(Push("Viewer", "ocean", clock(), "LIVE", "viewer"))
        session.drain()
        _ = [e async for e in session._answer("war")]
        assert not session.scoring.board.stream

    asyncio.run(run())


def test_rank_command_and_mvp_chat_cooldown():
    async def run():
        session, clock = session_with_clock()
        parser = ChatParser(session.library.concepts, bot_id="bot", broadcaster_id="channel")
        command = parser.parse(
            {
                "metadata": {"message_type": "notification"},
                "payload": {
                    "subscription": {"type": "channel.chat.message", "version": "1"},
                    "event": {
                        "broadcaster_user_id": "channel",
                        "chatter_user_id": "viewer",
                        "message_id": "rank",
                        "message": {"text": "!rank"},
                    },
                },
            }
        )
        assert isinstance(command, Rank)
        session.scoring.board.add("viewer", "Viewer", 8)
        await session.submit(command)
        reply = session.drain()[0]
        assert reply.phase == "rank" and "1; 8.00 points" in reply.message
        assert reply.message.startswith("@viewer ")
        card = json.dumps({"mvp": {"name": "Viewer", "points": 8}})

        async def events():
            yield reply
            yield Round("war", "mvp", 0, card)
            clock.advance(10)
            yield Round("war", "mvp", 1, card)
            clock.advance(50)
            yield Round("war", "mvp", 2, card)

        session.events = events
        live = LiveSession(session, "client", "channel")
        notices = []
        live.announce = notices.append
        await live._engine()
        assert notices[0] == reply.message
        assert len(notices) == 3
        assert sum(message.startswith("Round MVP:") for message in notices) == 2

    asyncio.run(run())


def test_rank_mention_does_not_expose_a_hidden_concept_name():
    from nous.engine.commands import Rank

    session, _ = session_with_clock()
    session.current_mode = "telepathy"
    session.telepathy.arm(set())
    session.pending.put_nowait(Rank("ocean", "viewer"))
    reply = session.drain()[0]
    assert reply.message.startswith("@Friend ")
    assert "ocean" not in reply.message.casefold()
