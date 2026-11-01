import argparse
import logging
import os
import secrets
import tempfile
import webbrowser
from pathlib import Path

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
    for serve in (demo, replay):
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
            2, "The evaluation harness is outside M2; no quality results have been produced.\n"
        )
    if args.command == "build-library":
        from thoughtquake.model.hf_backend import HFBackend

        backend = HFBackend()
        build_library(backend, load_concepts(), model_id=backend.model.config._name_or_path).save(
            args.output
        )
        return
    token = os.getenv("THOUGHTQUAKE_LOCAL_TOKEN")
    token_path: Path | None = None
    if not token:
        token = secrets.token_urlsafe(32)
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="thoughtquake-", suffix=".token.json", delete=False
        ) as handle:
            import json

            handle.write(json.dumps({"token": token}))
            token_path = Path(handle.name)
        token_path.chmod(0o600)
        log.info("Local broadcaster token (0600): %s", token_path)
    if args.command == "demo":
        backend = MockBackend()
        if not args.mock:
            try:
                from thoughtquake.model.tiny_backend import TinyBackend

                backend = TinyBackend()
            except ImportError:
                log.info("Optional model dependencies absent; using the offline mock")
        crowd = Crowd(load_script(args.script), users=args.users)
        session = Session(backend=backend, crowd=crowd)
        if args.record:
            session.recorder = Recorder(args.record, session.metadata(), clock=session.clock)
        app = create_app(
            source=session.events,
            concepts=session.library.concepts,
            switch_mode=session.switch_mode,
            control_token=token,
        )
    else:
        player = Player(args.file)
        if args.frames:
            source = lambda: player.frames(speed=args.speed)
            concepts = load_concepts()
        else:
            slug = player.metadata["model_slug"]
            replay_library = mock_library()
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
                Mixer(clock=clock),
                seed=player.metadata["seed"],
                clock=clock,
                source="REPLAY",
            )
            source = lambda: player.engine(engine, clock, speed=args.speed)
            concepts = engine.library.concepts
        app = create_app(source=source, concepts=concepts, control_token=token)
    url = f"http://{args.host}:{args.port}/"

    async def startup(application: web.Application) -> None:
        log.info("THOUGHTQUAKE overlay: %s", url)
        log.info("Static screenshot fixture: %sfixture.html", url)
        if not args.no_browser:
            webbrowser.open(url)

    async def cleanup(application: web.Application) -> None:
        if token_path:
            token_path.unlink(missing_ok=True)

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
