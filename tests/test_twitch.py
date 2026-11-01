import asyncio
import copy
import json
import os
import time
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from nous.concepts.library import load_concepts
from nous.engine.mixer import FakeClock
from nous.twitch.auth import SCOPES, AuthError, OAuth, Token, TokenStore
from nous.twitch.chat_send import ChatSender
from nous.twitch.eventsub import EVENTSUB_URL, EventSub
from nous.twitch.parse import ChatParser

FIXTURES = Path(__file__).parent / "fixtures/twitch"


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


class FakeTwitch:
    def __init__(self):
        self.app = web.Application()
        self.forms = []
        self.poll_errors = ["authorization_pending"]
        self.device_expiry = 30
        self.refresh_count = 0
        self.expire_helix_once = False
        self.invalid_scopes = False
        self.subscriptions = []
        self.posts = []
        self.chat_status = 200
        self.subscribed = asyncio.Event()
        self.welcome_at = None
        self.sockets = []
        self.script = None
        self.app.router.add_post("/oauth2/device", self.device)
        self.app.router.add_post("/oauth2/token", self.token)
        self.app.router.add_get("/oauth2/validate", self.validate)
        self.app.router.add_get("/helix/users", self.users)
        self.app.router.add_post("/helix/eventsub/subscriptions", self.subscribe)
        self.app.router.add_post("/helix/chat/messages", self.chat)
        self.app.router.add_get("/ws", self.websocket)
        self.app.router.add_get("/new", self.websocket)

    async def device(self, request):
        form = dict(await request.post())
        assert form == {"client_id": "public-client", "scopes": " ".join(SCOPES)}
        return web.json_response(
            {
                "device_code": "test-device",
                "expires_in": self.device_expiry,
                "interval": 2,
                "user_code": "TEST-CODE",
                "verification_uri": "https://example.invalid/activate",
            }
        )

    async def token(self, request):
        form = dict(await request.post())
        self.forms.append(form)
        assert "client_secret" not in form
        if form["grant_type"] == "refresh_token":
            self.refresh_count += 1
            assert form["refresh_token"] == "refresh-" + str(self.refresh_count - 1)
            return web.json_response(
                {
                    "access_token": "access-" + str(self.refresh_count),
                    "refresh_token": "refresh-" + str(self.refresh_count),
                    "expires_in": 3600,
                }
            )
        assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
        assert form["scopes"] == " ".join(SCOPES)
        assert form["device_code"] == "test-device"
        if self.poll_errors:
            return web.json_response({"message": self.poll_errors.pop(0)}, status=400)
        return web.json_response(
            {"access_token": "access-0", "refresh_token": "refresh-0", "expires_in": 3600}
        )

    async def validate(self, request):
        assert request.headers["Authorization"].startswith("OAuth access-")
        return web.json_response(
            {
                "client_id": "public-client",
                "user_id": "200",
                "login": "bot",
                "expires_in": 3600,
                "scopes": [] if self.invalid_scopes else list(SCOPES),
            }
        )

    async def users(self, request):
        assert request.query["login"] == "streamer"
        return web.json_response({"data": [{"id": "100", "login": "streamer"}]})

    async def subscribe(self, request):
        assert request.headers["Client-Id"] == "public-client"
        if self.expire_helix_once and request.headers["Authorization"] == "Bearer access-0":
            self.expire_helix_once = False
            return web.json_response({"message": "expired"}, status=401)
        body = await request.json()
        self.subscriptions.append(body)
        assert time.monotonic() - self.welcome_at < 10
        self.subscribed.set()
        return web.json_response({"data": [{"id": "sub-1", "status": "enabled"}]}, status=202)

    async def chat(self, request):
        self.posts.append(await request.json())
        return web.json_response(
            {"data": [{"message_id": "sent-1", "is_sent": True}]}, status=self.chat_status
        )

    async def websocket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        welcome = fixture("welcome")
        if request.path == "/new":
            welcome["payload"]["session"]["id"] = "session-2"
        self.welcome_at = time.monotonic()
        await ws.send_json(welcome)
        if self.script:
            await self.script(ws, request)
        else:
            await self.subscribed.wait()
            await ws.send_json(fixture("keepalive"))
            await ws.send_json(fixture("notification"))
        async for _ in ws:
            pass
        return ws

    def auth(self, http, server, store, clock=None):
        return OAuth(
            http,
            "public-client",
            store,
            token=Token("access-0", "refresh-0", 10**12, "200", "bot"),
            auth_base=str(server.make_url("/oauth2")),
            helix_base=str(server.make_url("/helix")),
            **({"clock": clock, "monotonic": clock} if clock else {}),
        )


def test_device_pending_success_and_atomic_token_store(tmp_path):
    async def run():
        api = FakeTwitch()
        clock = FakeClock(1000)
        delays = []

        async def sleep(seconds):
            delays.append(seconds)
            clock.advance(seconds)

        store = TokenStore(tmp_path / "private/token.json")
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            auth = api.auth(http, server, store, clock)
            auth.sleep = sleep
            shown = []
            token = await auth.authorize(lambda uri, code: shown.append((uri, code)))
            assert shown == [("https://example.invalid/activate", "TEST-CODE")]
            assert delays == [2, 2]
            assert token.user_id == "200" and token.login == "bot"
            assert store.load() == token
            assert os.stat(store.path).st_mode & 0o777 == 0o600
            assert not list(store.path.parent.glob("*.tmp"))
            assert token.access_token not in repr(token)
            assert token.refresh_token not in repr(token)

    asyncio.run(run())


@pytest.mark.parametrize(
    "errors,expiry,expected",
    [
        (["slow_down", "authorization_pending"], 30, [2, 7, 7]),
        (["authorization_pending"] * 5, 5, [2, 2]),
        (["access_denied"], 30, [2]),
    ],
)
def test_device_slow_down_expiry_and_denial(tmp_path, errors, expiry, expected):
    async def run():
        api = FakeTwitch()
        api.poll_errors, api.device_expiry = list(errors), expiry
        clock = FakeClock()
        delays = []

        async def sleep(seconds):
            delays.append(seconds)
            clock.advance(seconds)

        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            auth = api.auth(http, server, TokenStore(tmp_path / "token.json"), clock)
            auth.sleep = sleep
            if errors[0] == "slow_down":
                await auth.authorize(lambda *_: None)
            else:
                with pytest.raises(AuthError):
                    await auth.authorize(lambda *_: None)
            assert delays == expected
            assert clock() < expiry

    asyncio.run(run())


def test_proactive_refresh_serializes_one_use_token_and_validates_scopes(tmp_path):
    async def run():
        api = FakeTwitch()
        clock = FakeClock(1000)
        store = TokenStore(tmp_path / "token.json")
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            auth = api.auth(http, server, store, clock)
            auth.token = Token("access-0", "refresh-0", 1299, "200", "bot")
            tokens = await asyncio.gather(auth.access(), auth.access())
            assert api.refresh_count == 1
            assert tokens[0] == tokens[1] == store.load()
            assert store.load().refresh_token == "refresh-1"
            api.invalid_scopes = True
            with pytest.raises(AuthError, match="scopes"):
                await auth.validate()

    asyncio.run(run())


def test_full_happy_path_refresh_401_parse_send_and_dedupe(tmp_path):
    async def run():
        api = FakeTwitch()
        api.expire_helix_once = True

        async def script(ws, request):
            await api.subscribed.wait()
            await ws.send_json(fixture("keepalive"))
            await ws.send_json(fixture("notification"))
            await ws.send_json(fixture("notification"))
            other = fixture("notification")
            other["metadata"]["message_id"] = "new-envelope"
            other["payload"]["event"]["message_id"] = "chat-2"
            await ws.send_json(other)

        api.script = script
        store = TokenStore(tmp_path / "token.json")
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            auth = api.auth(http, server, store)
            states = []

            async def status(value):
                states.append(value)

            client = EventSub(auth, "100", "200", url=str(server.make_url("/ws")), status=status)
            stream = client.notifications()
            try:
                first, second = await anext(stream), await anext(stream)
                parser = ChatParser(
                    load_concepts(), bot_id="200", broadcaster_id="100", clock=lambda: 7
                )
                push = parser.parse(first)
                assert push.faction == "space" and push.user == "Friend"
                assert push.user_id == "300" and push.source == "LIVE" and push.t == 7
                assert parser.parse(first) is None
                assert parser.parse(second).faction == "space"
                assert api.refresh_count == 1
                assert store.load().refresh_token == "refresh-1"
                assert api.subscriptions == [
                    {
                        "type": "channel.chat.message",
                        "version": "1",
                        "condition": {"broadcaster_user_id": "100", "user_id": "200"},
                        "transport": {"method": "websocket", "session_id": "session-1"},
                    }
                ]
                assert states == ["connected"]
                assert await ChatSender(auth, "100", "200").send("Team Space leads Mind Share.")
                assert api.posts[-1]["sender_id"] == "200"
            finally:
                await stream.aclose()

    asyncio.run(run())


def test_chat_rate_limit_trimming_and_nonfatal_failure(tmp_path):
    async def run():
        api = FakeTwitch()
        clock = FakeClock()
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            sender = ChatSender(
                api.auth(http, server, TokenStore(tmp_path / "token.json")),
                "100",
                "200",
                clock=clock,
            )
            assert await sender.send("  " + "a" * 250 + "  ")
            assert len(api.posts[-1]["message"]) == 200
            assert not await sender.send("too soon")
            clock.advance(4.999)
            assert not await sender.send("still too soon")
            clock.advance(0.001)
            assert await sender.send("now")
            clock.advance(5)
            api.chat_status = 429
            assert not await sender.send("failure is ignored")
            assert len(api.posts) == 3

    asyncio.run(run())


def test_parser_whole_words_first_match_own_bot_channel_and_identity(library):
    parser = ChatParser(load_concepts(), bot_id="200", broadcaster_id="100")
    message = fixture("notification")
    assert parser.parse(message).faction == "space"
    changed = copy.deepcopy(message)
    changed["metadata"]["message_id"] = "other-envelope-same-chat"
    assert parser.parse(changed) is None
    for text, expected in [("!push SEA", "ocean"), ("research", None), ("wave then star", "ocean")]:
        changed = fixture("notification")
        changed["payload"]["event"]["message_id"] = text
        changed["payload"]["event"]["message"]["text"] = text
        result = parser.parse(changed)
        assert (result.faction if result else None) == expected
    changed = fixture("notification")
    changed["payload"]["event"]["chatter_user_id"] = "200"
    assert parser.parse(changed) is None
    changed["payload"]["event"]["chatter_user_id"] = "400"
    changed["payload"]["event"]["broadcaster_user_id"] = "other-channel"
    assert parser.parse(changed) is None
    assert parser.parse(fixture("keepalive")) is None
    assert "keepalive_timeout_seconds=30" in EVENTSUB_URL


def test_session_reconnect_opens_new_before_old_closes_without_resubscribe(tmp_path):
    async def run():
        api = FakeTwitch()
        states, new_open_checks = [], []

        async def status(value):
            states.append(value)

        async def script(ws, request):
            if request.path == "/ws":
                await api.subscribed.wait()
                await ws.send_json(fixture("notification"))
                reconnect = fixture("reconnect")
                reconnect["payload"]["session"]["reconnect_url"] = str(server.make_url("/new"))
                await ws.send_json(reconnect)
                tail = fixture("notification")
                tail["metadata"]["message_id"] = "old-tail"
                tail["payload"]["event"]["message_id"] = "old-tail-chat"
                await ws.send_json(tail)
            else:
                new_open_checks.append(not api.sockets[0].closed)
                notification = fixture("notification")
                notification["metadata"]["message_id"] = "new-notification"
                notification["payload"]["event"]["message_id"] = "new-chat"
                await ws.send_json(notification)

        api.script = script
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            client = EventSub(
                api.auth(http, server, TokenStore(tmp_path / "token.json")),
                "100",
                "200",
                url=str(server.make_url("/ws")),
                status=status,
            )
            stream = client.notifications()
            try:
                async with asyncio.timeout(2):
                    messages = [await anext(stream) for _ in range(3)]
                assert {m["metadata"]["message_id"] for m in messages} == {
                    "notification-envelope",
                    "old-tail",
                    "new-notification",
                }
                assert new_open_checks == [True]
                assert len(api.subscriptions) == 1
                assert states == ["connected", "reconnecting", "connected"]
            finally:
                await stream.aclose()

    asyncio.run(run())


def test_unplanned_disconnect_reconnects_with_resubscribe(tmp_path):
    async def run():
        api = FakeTwitch()
        delays = []

        async def sleep(delay):
            delays.append(delay)
            await asyncio.sleep(0)

        async def script(ws, request):
            await api.subscribed.wait()
            message = fixture("notification")
            message["metadata"]["message_id"] = f"connection-{len(api.sockets)}"
            await ws.send_json(message)
            if len(api.sockets) == 1:
                await ws.close(code=1011)

        api.script = script
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            client = EventSub(
                api.auth(http, server, TokenStore(tmp_path / "token.json")),
                "100",
                "200",
                url=str(server.make_url("/ws")),
                sleep=sleep,
            )
            stream = client.notifications()
            try:
                async with asyncio.timeout(2):
                    assert (await anext(stream))["metadata"]["message_id"] == "connection-1"
                    assert (await anext(stream))["metadata"]["message_id"] == "connection-2"
                assert len(api.subscriptions) == 2
                assert delays == [1]
            finally:
                await stream.aclose()

    asyncio.run(run())


def test_revocation_is_terminal_and_reports_status(tmp_path):
    async def run():
        api = FakeTwitch()
        states = []

        async def status(value):
            states.append(value)

        async def script(ws, request):
            await api.subscribed.wait()
            await ws.send_json(fixture("revocation"))

        api.script = script
        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            client = EventSub(
                api.auth(http, server, TokenStore(tmp_path / "token.json")),
                "100",
                "200",
                url=str(server.make_url("/ws")),
                status=status,
            )
            async with asyncio.timeout(2):
                assert [message async for message in client.notifications()] == []
            assert states == ["connected", "revoked"]
            assert len(api.subscriptions) == 1

    asyncio.run(run())


def test_missing_welcome_uses_capped_exponential_backoff(tmp_path):
    class Finished(Exception):
        pass

    async def run():
        api = FakeTwitch()

        async def silent(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for _ in ws:
                pass
            return ws

        api.app.router.add_get("/silent", silent)
        delays = []

        async def sleep(value):
            delays.append(value)
            if len(delays) == 4:
                raise Finished

        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            client = EventSub(
                api.auth(http, server, TokenStore(tmp_path / "token.json")),
                "100",
                "200",
                url=str(server.make_url("/silent")),
                welcome_timeout=0.01,
                backoff_max=4,
                sleep=sleep,
            )
            with pytest.raises(Finished):
                async with asyncio.timeout(2):
                    await anext(client.notifications())
            assert delays == [1, 2, 4, 4]

    asyncio.run(run())


def test_ping_does_not_hide_keepalive_timeout(tmp_path):
    async def run():
        api = FakeTwitch()

        async def timeout_socket(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            api.sockets.append(ws)
            welcome = fixture("welcome")
            welcome["payload"]["session"]["keepalive_timeout_seconds"] = 0.02
            api.welcome_at = time.monotonic()
            await ws.send_json(welcome)
            await api.subscribed.wait()
            if len(api.sockets) == 1:
                try:
                    for _ in range(20):
                        await ws.ping()
                        await asyncio.sleep(0.003)
                except ConnectionError:
                    pass
            else:
                await ws.send_json(fixture("notification"))
            async for _ in ws:
                pass
            return ws

        api.app.router.add_get("/timeout", timeout_socket)

        async def sleep(_):
            await asyncio.sleep(0)

        async with TestServer(api.app) as server, aiohttp.ClientSession() as http:
            client = EventSub(
                api.auth(http, server, TokenStore(tmp_path / "token.json")),
                "100",
                "200",
                url=str(server.make_url("/timeout")),
                keepalive_grace=0,
                sleep=sleep,
            )
            stream = client.notifications()
            try:
                async with asyncio.timeout(2):
                    assert (await anext(stream))["metadata"]["message_type"] == "notification"
                assert len(api.subscriptions) == 2
            finally:
                await stream.aclose()

    asyncio.run(run())


def test_atomic_store_keeps_old_file_if_replace_fails(monkeypatch, tmp_path):
    store = TokenStore(tmp_path / "token.json")
    old = Token("old", "refresh-old", 1)
    store.save(old)

    def fail(*args):
        raise OSError("test write failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save(Token("new", "refresh-new", 2))
    assert store.load() == old
    assert not list(tmp_path.glob("*.tmp"))


def test_live_session_routes_pushes_records_and_disables_crowd(tmp_path):
    from nous.engine.events import Badge, Connection, Push
    from nous.replay.player import Player
    from nous.server.session import Session
    from nous.sim.crowd import Crowd
    from nous.twitch.live import LiveSession

    async def run():
        api = FakeTwitch()
        store = TokenStore(tmp_path / "token.json")
        store.save(Token("access-0", "refresh-0", 10**12, "200", "bot"))
        session = Session(crowd=Crowd(twitch_connected=True), source="LIVE")
        path = tmp_path / "live.jsonl"
        async with TestServer(api.app) as server:
            live = LiveSession(
                session,
                "public-client",
                "streamer",
                store=store,
                record=path,
                auth_base=str(server.make_url("/oauth2")),
                helix_base=str(server.make_url("/helix")),
                eventsub_url=str(server.make_url("/ws")),
            )
            stream = live.events()
            output = []
            try:
                async with asyncio.timeout(3):
                    async for event in stream:
                        output.append(event)
                        if isinstance(event, Push):
                            break
            finally:
                await stream.aclose()
        assert isinstance(output[0], Badge) and output[0].label == "LIVE"
        assert output[0].simulated_users is None
        assert sum(isinstance(e, Badge) for e in output) == 1
        assert any(isinstance(e, Connection) and e.state == "connected" for e in output)
        assert output[-1].source == "LIVE" and output[-1].faction == "space"
        assert not session.crowd.enabled
        player = Player(path)
        assert player.metadata["config"]["source"] == "LIVE"
        text = path.read_text()
        assert "access-0" not in text and "refresh-0" not in text

    asyncio.run(run())


def test_twitch_identity_spam_control_survives_display_name_change():
    from nous.engine.events import Push
    from nous.engine.mixer import Mixer

    clock = FakeClock()
    mixer = Mixer(clock=clock)
    assert mixer.push(Push("NameOne", "ocean", 0, "LIVE", user_id="300")) == 1
    assert mixer.push(Push("NameTwo", "space", 0, "LIVE", user_id="300")) == 0.25
    assert mixer.push(Push("NameThree", "space", 0, "LIVE", user_id="300")) == 0.25
    assert mixer.push(Push("NameFour", "space", 0, "LIVE", user_id="300")) == 0


def test_explicit_simulation_retains_secondary_badge_in_live_and_replay(tmp_path):
    from nous.engine.events import Badge, Connection
    from nous.replay.player import Player
    from nous.replay.recorder import Recorder
    from nous.server.session import Session
    from nous.server.state import ViewState
    from nous.sim.crowd import Crowd

    async def badge():
        session = Session(crowd=Crowd(twitch_connected=True, explicit_sim=True), source="LIVE")
        iterator = session.events()
        try:
            return await anext(iterator)
        finally:
            await iterator.aclose()

    event = asyncio.run(badge())
    assert isinstance(event, Badge) and event.label == "LIVE" and event.simulated_users == 40
    path = tmp_path / "live-sim.jsonl"
    meta = {
        "config": {},
        "seed": 0,
        "model_slug": "mock",
        "library_hash": "fixture",
        "app_version": "0.1.0",
    }
    with Recorder(path, meta) as recorder:
        recorder.record(event)
        recorder.record(Connection("twitch", "reconnecting"))
    restored = next(Player(path).frame_events())[1]
    assert restored.label == "REPLAY" and restored.simulated_users == 40
    state = ViewState()
    state.apply(Connection("twitch", "reconnecting"))
    assert state.snapshot().state["connections"]["twitch"] == "reconnecting"


def test_live_recording_closes_even_before_workers_start(monkeypatch, tmp_path):
    from nous.server.session import Session
    from nous.sim.crowd import Crowd
    from nous.twitch import live

    instances = []
    real_recorder = live.Recorder

    class TrackingRecorder(real_recorder):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(live, "Recorder", TrackingRecorder)

    async def run():
        session = Session(crowd=Crowd(twitch_connected=True), source="LIVE")
        connection = live.LiveSession(
            session, "public-client", "streamer", record=tmp_path / "partial.jsonl"
        )
        stream = connection.events()
        assert (await anext(stream)).label == "LIVE"
        await stream.aclose()
        assert instances[0].file.closed

    asyncio.run(run())
