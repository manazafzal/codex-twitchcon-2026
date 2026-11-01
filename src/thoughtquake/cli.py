import argparse
import asyncio
import logging
import os
import re
import secrets
import webbrowser
from pathlib import Path

import aiohttp
from aiohttp import web

from thoughtquake.concepts.builder import build_library
from thoughtquake.concepts.library import ConceptLibrary, load_concepts
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.replay.player import Player
from thoughtquake.replay.recorder import Recorder
from thoughtquake.server.app import create_app
from thoughtquake.server.session import Session, mock_library
from thoughtquake.sim.crowd import Crowd, load_script

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="THOUGHTQUAKE local thought injection game")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Serve the offline simulated crowd and overlay")
    demo.add_argument(
        "--mock", action="store_true", help="Use deterministic TINY MODEL / CI output"
    )
    demo.add_argument("--script", type=Path, help="Seeded crowd script")
    demo.add_argument("--users", type=int, default=40)
    demo.add_argument("--record", type=Path, help="Record input and output events to JSONL")
    replay = commands.add_parser("replay", help="Serve a recorded session with a REPLAY badge")
    replay.add_argument("file", type=Path)
    modes = replay.add_mutually_exclusive_group()
    modes.add_argument(
        "--frames", action="store_true", help="Render recorded frames without a model"
    )
    modes.add_argument(
        "--engine", action="store_true", help="Regenerate from recorded pushes (default)"
    )
    replay.add_argument("--speed", type=float, default=1)
    replay.add_argument("--library", type=Path, help="Concept library for real-model engine replay")
    commands.add_parser("auth", help="Sign in to Twitch with a Public app Device Code")
    run = commands.add_parser("run", help="Serve live Twitch chat with the LIVE source badge")
    run.add_argument("--channel", required=True)
    run.add_argument("--sim", action="store_true", help="Explicitly add a labelled simulated crowd")
    run.add_argument("--record", type=Path)
    run.add_argument("--mock", action="store_true", help="Use TINY MODEL / CI with real chat input")
    run.add_argument(
        "--library", type=Path, help="Real-model library; otherwise use TINY MODEL / CI"
    )
    for configured in (demo, run):
        configured.add_argument(
            "--colour-source", choices=("applied", "readout"), default="applied"
        )
        configured.add_argument(
            "--schedule-mode", choices=("answer", "sentence", "token"), default="answer"
        )
    for serve in (demo, replay, run):
        serve.add_argument(
            "--eval-file", type=Path, help="Real-model evidence required for Mind-Reader colours"
        )
        serve.add_argument("--host", default="127.0.0.1")
        serve.add_argument("--port", type=int, default=8080)
        serve.add_argument("--no-browser", action="store_true")
    commands.add_parser("eval", help="Reserved for the evaluation milestone")
    build = commands.add_parser(
        "build-library", help="Generate a library with the local real model"
    )
    build.add_argument("--output", type=Path, default=Path("library/qwen2.5-0.5b-instruct.npz"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "eval":
        parser.exit(
            2, "The evaluation harness is outside M4; no quality results have been produced.\n"
        )
    if args.command == "build-library":
        from thoughtquake.model.hf_backend import HFBackend

        backend = HFBackend()
        build_library(backend, load_concepts(), model_id=backend.model.config._name_or_path).save(
            args.output
        )
        return
    client_id = os.getenv("THOUGHTQUAKE_TWITCH_CLIENT_ID", "")
    if args.command in {"auth", "run"} and not client_id:
        parser.error("Set THOUGHTQUAKE_TWITCH_CLIENT_ID to your Public app's client ID")
    if args.command == "auth":
        from thoughtquake.twitch.auth import AuthError, OAuth, TokenStore

        async def login() -> None:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15), trust_env=True
            ) as http:
                auth = OAuth(http, client_id, TokenStore())
                token = await auth.authorize(
                    lambda uri, code: log.info("Open %s · Code: %s", uri, code)
                )
                log.info("Authenticated Twitch user: %s", token.login)

        try:
            asyncio.run(login())
        except (AuthError, aiohttp.ClientError, TimeoutError) as exc:
            parser.exit(
                1, (str(exc) if isinstance(exc, AuthError) else "Twitch login unavailable") + "\n"
            )
        return
    if args.command == "run":
        from thoughtquake.twitch.auth import AuthError, TokenStore

        if not re.fullmatch(r"[a-zA-Z0-9_]{1,25}", args.channel):
            parser.error("Use the channel login name without a URL or #")
        try:
            TokenStore().load()
        except AuthError as exc:
            parser.error(str(exc))
    token = secrets.token_urlsafe(32)
    log.info("Local control token for this run: %s", token)
    if args.command == "demo":
        backend = MockBackend()
        if not args.mock:
            try:
                from thoughtquake.model.tiny_backend import TinyBackend

                backend = TinyBackend()
            except ImportError:
                log.info("Optional model dependencies absent; using the offline mock")
        crowd = Crowd(load_script(args.script), users=args.users)
        session = Session(
            backend=backend,
            crowd=crowd,
            colour_source=args.colour_source,
            eval_path=args.eval_file,
            schedule_mode=args.schedule_mode,
        )
        if args.record:
            session.recorder = Recorder(args.record, session.metadata(), clock=session.clock)
        app = create_app(
            source=session.events,
            concepts=session.library.concepts,
            switch_mode=session.switch_mode,
            set_immune=session.set_immune,
            control_token=token,
        )
    elif args.command == "run":
        from thoughtquake.twitch.live import LiveSession

        backend = MockBackend()
        library = mock_library(all_concepts=True)
        if args.library and not args.mock:
            from thoughtquake.model.hf_backend import HFBackend

            library = ConceptLibrary.load(args.library)
            backend = HFBackend()
        crowd = Crowd(twitch_connected=True, explicit_sim=args.sim)
        session = Session(
            backend=backend,
            library=library,
            crowd=crowd,
            source="LIVE",
            colour_source=args.colour_source,
            eval_path=args.eval_file,
            schedule_mode=args.schedule_mode,
        )
        live = LiveSession(session, client_id, args.channel.lower(), record=args.record)
        app = create_app(
            source=live.events,
            concepts=library.concepts,
            control_token=token,
            switch_mode=session.switch_mode,
            set_immune=session.set_immune,
        )
    else:
        player = Player(args.file)
        if args.frames:
            source = lambda: player.frames(speed=args.speed)
            concepts = load_concepts()
        else:
            slug = player.metadata["model_slug"]
            replay_library = mock_library(
                all_concepts=player.metadata["config"].get("all_concepts", False)
            )
            replay_backend = MockBackend()
            if slug == "tiny":
                from thoughtquake.model.tiny_backend import TinyBackend

                replay_backend = TinyBackend(seed=player.metadata.get("backend_seed", 0))
            elif slug != "mock":
                from thoughtquake.model.hf_backend import HFBackend

                if args.library is None:
                    parser.error(
                        "Real-model engine replay requires --library; --frames needs no model"
                    )
                replay_library = ConceptLibrary.load(args.library)
                replay_backend = HFBackend(slug)
            clock = FakeClock()
            engine = Generator(
                replay_backend,
                replay_library,
                Mixer(clock=clock, schedule_mode=player.metadata["config"]["schedule_mode"]),
                seed=player.metadata["seed"],
                clock=clock,
                source="REPLAY",
                colour_source=player.metadata["config"].get("colour_source", "applied"),
                eval_path=args.eval_file,
            )
            source = lambda: player.engine(engine, clock, speed=args.speed)
            concepts = engine.library.concepts
        app = create_app(source=source, concepts=concepts, control_token=token)
    url = f"http://{args.host}:{args.port}/"

    async def startup(application: web.Application) -> None:
        log.info("THOUGHTQUAKE overlay: %s", url)
        log.info("Static screenshot fixture: %sfixture.html", url)
        log.info("Broadcaster controls: %scontrol", url)
        if not args.no_browser:
            webbrowser.open(url)

    app.on_startup.append(startup)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
