import asyncio
import json
import re
from dataclasses import replace

from aiohttp.test_utils import TestClient, TestServer

from thoughtquake.concepts.library import load_concepts
from thoughtquake.engine.events import Guess, Layout, Mode, Push, Tamper, Tick, Token
from thoughtquake.replay.recorder import Recorder
from thoughtquake.server.app import APP_KEY, create_app
from thoughtquake.server.leaderboard import Leaderboard
from thoughtquake.server.secrecy import BlindProjection


def payload_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for row in value:
            yield from payload_strings(row)
    elif isinstance(value, dict):
        for key, row in value.items():
            # Fixed schema keys are public grammar, not a concept payload.
            if key in {c.id for c in load_concepts()}:
                yield key
            yield from payload_strings(row)


def assert_private(value):
    strings = list(payload_strings(value))
    for concept in load_concepts():
        aliases = (concept.id, concept.label, *concept.aliases)
        pattern = re.compile(
            r"(?<!\w)(?:" + "|".join(map(re.escape, aliases)) + r")(?!\w)", re.IGNORECASE
        )
        assert not any(pattern.search(text) for text in strings), concept.id


def token(text, i=0):
    return Token(
        i,
        text,
        "weather",
        {"scores": {"weather": 8, "ocean": 1}, "top": "weather", "margin": 7},
        "weather",
        {
            "z": {"weather": 8},
            "pulse": {"weather": 1},
            "drive": 0.3,
            "residual": 1,
            "median": 1,
            "clamp": 0,
            "calibrated": True,
        },
    )


def test_split_fragments_and_whole_words_never_escape():
    public = BlindProjection(load_concepts())
    public.event(
        Mode(
            "telepathy", False, "Make tea.", 1, phase="generating", round_id=1, injection="weather"
        )
    )
    output = []
    for i, text in enumerate(("sto", "rm", " is ", "near", "by. ")):
        event = public.event(token(text, i))
        output.append(event.text)
        assert_private(event.to_dict())
    tail = public.finish_token()
    if tail:
        output.append(tail.text)
    assert "storm" not in "".join(output).casefold()
    assert "\u2592" in "".join(output)
    assert public.opaque("weather").startswith("voc")


def test_recording_client_whole_blind_round_api_html_and_board(tmp_path):
    async def run():
        concepts = load_concepts()
        board = Leaderboard()
        board.add("7", "Storm", 10, "weather")
        app = create_app(concepts=concepts, leaderboard=board)
        async with TestClient(TestServer(app)) as client:
            server = app[APP_KEY]
            await server.publish(Layout({c.id: [i / 30, 0] for i, c in enumerate(concepts)}))
            # Prior public state must not reappear in a new blind-round snapshot.
            await server.publish(token("Ocean and storm."))
            await server.publish(
                Mode(
                    "telepathy",
                    False,
                    "Make tea.",
                    1,
                    phase="armed",
                    round_id=1,
                    injection="weather",
                )
            )
            async with client.ws_connect("/ws") as ws:
                assert_private(await ws.receive_json())
                sequence = [
                    Mode(
                        "telepathy",
                        False,
                        "Make tea.",
                        1,
                        phase="generating",
                        round_id=1,
                        injection="weather",
                    ),
                    Push("Sea", "weather", 0, "LIVE", "7"),
                    Tick({"weather": 0.7, "Neutral": 0.3}, 1, [], 0),
                    Guess("Star", "storm", 1, "LIVE", "8"),
                    Tamper(("weather",), 0.5),
                    token("sto", 0),
                    token("rm ", 1),
                    token("by the ", 2),
                    token("sea. ", 3),
                    Mode(
                        "telepathy",
                        False,
                        "Make tea.",
                        1,
                        phase="guessing",
                        round_id=1,
                        injection="weather",
                    ),
                ]
                for event in sequence:
                    await server.publish(event)
                    # A sentinel status lets the client drain all emitted layout/text frames.
                    from thoughtquake.engine.events import Connection

                    await server.publish(Connection("test", "boundary"))
                    while True:
                        frame = await ws.receive_json()
                        assert_private(frame)
                        if frame.get("kind") == "connection" and frame["state"] == "boundary":
                            break
                    assert_private(await (await client.get("/api/state")).json())
                    assert_private(await (await client.get("/api/leaderboard")).json())
                html = await (await client.get("/")).text()
                assert ">WAR<" not in html
                await server.publish(
                    Mode(
                        "telepathy",
                        False,
                        "Make tea.",
                        1,
                        phase="reveal",
                        round_id=1,
                        reveal="weather",
                    )
                )
                state = await (await client.get("/api/state")).json()
                assert state["mode"]["reveal"] == "weather"
                assert state["layout"]["alias"] and state["concepts"]

    asyncio.run(run())


def test_raw_snapshots_are_scrubbed_and_logs_hold_until_reveal(tmp_path):
    from thoughtquake.server.state import ViewState

    library = load_concepts()
    state = ViewState(library)
    mode = Mode(
        "telepathy",
        False,
        "Describe weather.",
        1,
        phase="generating",
        round_id=1,
        injection="weather",
    )
    state.apply(mode)
    state.apply(token("A storm at sea."))
    projection = BlindProjection(library)
    projected = projection.event(state.snapshot())
    assert_private(projected.to_dict())
    metadata = {
        "config": {"sim_script": {"waves": [{"faction": "weather"}]}},
        "seed": 0,
        "model_slug": "mock",
        "library_hash": "abcd",
        "app_version": "test",
    }
    path = tmp_path / "round.jsonl"
    recorder = Recorder(path, metadata, clock=lambda: 0)
    recorder.record(mode)
    recorder.record(token("storm"))
    before = [json.loads(row) for row in path.read_text().splitlines()]
    assert_private(before)
    recorder.record(replace(mode, phase="reveal", reveal="weather"))
    recorder.release()
    recorder.close()
    assert "weather" in path.read_text()
    path2 = tmp_path / "cancelled.jsonl"
    recorder = Recorder(path2, metadata, clock=lambda: 0)
    recorder.record(mode)
    recorder.record(token("storm"))
    recorder.close()
    assert_private([json.loads(row) for row in path2.read_text().splitlines()])


def test_multiword_names_are_masked_before_chunking_and_ids_are_not_canonical():
    public = BlindProjection(load_concepts())
    public.event(Mode("telepathy", False, "Make tea.", 1, phase="generating", round_id=1))
    first = dict(public.ids)
    result = ""
    for text in ("Time ", "trav", "el ", "is ", "odd. "):
        result += public.event(token(text)).text
    tail = public.finish_token()
    if tail:
        result += tail.text
    assert "time travel" not in result.casefold() and "\u2592" in result
    assert [first[c.id] for c in load_concepts()] != [f"voc{i:03}" for i in range(30)]
    public.event(Mode("telepathy", False, "Make tea.", 1, phase="reveal", round_id=1))
    public.event(Mode("telepathy", False, "Make tea.", 2, phase="generating", round_id=2))
    assert first != public.ids
