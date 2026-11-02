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

from nous.concepts.builder import build_library
from nous.concepts.library import ConceptLibrary, load_concepts
from nous.config import data_dir, library_path, model_dir, user_library_path
from nous.engine.generate import Generator
from nous.engine.mixer import FakeClock, Mixer
from nous.model.mock_backend import MockBackend
from nous.replay.player import Player
from nous.replay.recorder import Recorder
from nous.server.app import create_app
from nous.server.session import Session, mock_library
from nous.sim.crowd import Crowd, load_script

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NOUS local thought injection game")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Open the welcome screen")
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
        "--library",
        type=Path,
        default=library_path(),
        help="Custom library; defaults to your saved library or the bundled fitted library",
    )
    run.add_argument(
        "--model-path", type=Path, default=model_dir(), help="Local AI folder from setup"
    )
    for configured in (demo, run):
        configured.add_argument(
            "--colour-source", choices=("applied", "readout"), default="applied"
        )
        configured.add_argument(
            "--schedule-mode", choices=("answer", "sentence", "token"), default="answer"
        )
    for serve in (start, demo, replay, run):
        serve.add_argument(
            "--eval-file", type=Path, help="Real-model evidence required for Mind-Reader colours"
        )
        serve.add_argument("--host", default="127.0.0.1")
        serve.add_argument("--port", type=int, default=8080)
        serve.add_argument("--no-browser", action="store_true")
    evaluation = commands.add_parser(
        "eval", help="Run matched local evaluation with concept-cluster intervals"
    )
    evaluation.add_argument(
        "--library", type=Path, default=Path("library/qwen2.5-0.5b-instruct.npz")
    )
    evaluation.add_argument("--output", type=Path, default=Path("results"))
    evaluation.add_argument("--alphas", type=float, nargs="+", default=[0.3, 0.45])
    evaluation.add_argument("--seeds", type=int, default=1)
    evaluation.add_argument("--prompts", type=int, default=6)
    evaluation.add_argument("--concepts", type=int, default=30)
    evaluation.add_argument("--held-out", type=int, default=3)
    evaluation.add_argument("--seed", type=int, default=0)
    evaluation.add_argument(
        "--mock", action="store_true", help="Run explicitly labelled TINY MODEL / CI evidence"
    )
    evaluation.add_argument(
        "--tiny", action="store_true", help="Use the random-init local test model"
    )
    evaluation.add_argument(
        "--model-path", type=Path, help="Local trained weights; no download is attempted"
    )
    fit = commands.add_parser(
        "fit-readout", help="Fit a v4 readout with disjoint families and seeds"
    )
    fit.add_argument("--library", type=Path, required=True)
    fit.add_argument("--output", type=Path)
    fit.add_argument(
        "--data", type=Path, help="Local NPZ split data; otherwise generate the training corpus"
    )
    fit.add_argument("--model-path", type=Path)
    fit.add_argument("--seed", type=int, default=0)
    alarm = commands.add_parser(
        "calibrate-alarm", help="Fit alarm thresholds from fresh uninjected generations"
    )
    alarm.add_argument("--library", type=Path, required=True)
    alarm.add_argument("--output", type=Path)
    alarm.add_argument("--seed", type=int, default=1)
    alarm.add_argument("--generations", type=int, default=60)
    alarm.add_argument("--model-path", type=Path)
    build = commands.add_parser(
        "build-library", help="Generate a library with the local real model"
    )
    build.add_argument("--output", type=Path, default=Path("library/qwen2.5-0.5b-instruct.npz"))
    build.add_argument("--variant", choices=("others", "neutral"), default="others")
    build.add_argument("--seed", type=int, default=0)
    build.add_argument("--samples", type=int, default=8)
    build.add_argument("--neutral-generations", type=int, default=60)
    build.add_argument("--model-path", type=Path)
    build.add_argument("--median-norm", type=float, default=26.78)
    research = commands.add_parser("research", help="Regenerate registered local research")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    study = research_sub.add_parser("run", help="Run offline ablations or record missing artifacts")
    study.add_argument("--config", type=Path, default=Path("configs/ablations.yaml"))
    study.add_argument("--seed", type=int, default=0)
    study.add_argument("--output", type=Path, default=Path("research"))
    concept = commands.add_parser("concept", help="Build and test a new chat topic")
    concept_sub = concept.add_subparsers(dest="concept_command", required=True)
    add = concept_sub.add_parser("add", help="Keep a topic private until it passes testing")
    add.add_argument("name")
    inputs = add.add_mutually_exclusive_group()
    inputs.add_argument("--from-model", type=int, default=24, metavar="N")
    inputs.add_argument("--examples", type=Path)
    add.add_argument("--library", type=Path)
    add.add_argument("--model-path", type=Path, default=model_dir())
    add.add_argument("--output", type=Path, default=data_dir() / "topics")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "concept":
        from nous.concepts.policy import validate_name
        from nous.concepts.topics import (
            BuildResult,
            TopicBuilder,
            load_examples,
            save_result,
            unavailable,
        )
        from nous.model.hf_backend import HFBackend

        try:
            name = validate_name(args.name)
        except ValueError as exc:
            parser.exit(1, str(exc) + "\n")
        examples = None
        try:
            examples = load_examples(args.examples) if args.examples else None
            library = ConceptLibrary.load(args.library or library_path())
            backend = HFBackend(local_path=str(args.model_path))
            result = TopicBuilder(backend, library).build(
                name, count=args.from_model, examples=examples
            )
        except (OSError, ValueError, ImportError) as exc:
            result = BuildResult(
                unavailable(name, f"Local build unavailable: {type(exc).__name__}")
            )
        if result.report["source"] == "unavailable":
            from nous.concepts.library import config_hash

            result.report["origin"].update(
                source="examples" if args.examples else "from-model",
                texts=examples if examples is not None else [],
                requested_count=len(examples) if examples is not None else args.from_model,
                texts_hash=config_hash({"texts": examples}) if examples is not None else None,
            )
        save_result(result, args.output / name)
        if result.library is not None and result.report["status"] == "accepted":
            result.library.save(args.library or user_library_path())
        log.info(
            "Topic %s: %s; report: %s",
            name,
            result.report["status"],
            args.output / name / "quality.json",
        )
        return
    if args.command == "research":
        from nous.research.runner import run_research

        run_research(args.config, args.seed, args.output)
        return
    if args.command in {"eval", "fit-readout", "calibrate-alarm", "build-library"}:
        from nous.concepts.builder import calibrate_alarm
        from nous.evaluation import evaluate, fit_readout, generate_training, write_report
        from nous.model.hf_backend import HFBackend

        try:
            if args.command == "fit-readout" and args.data:
                library = ConceptLibrary.load(args.library)
                backend = None
                source = "realmodel"
            elif args.command == "eval" and args.mock:
                backend = MockBackend()
                library = mock_library()
                library.config.update(
                    probe_layers=[backend.readout_layer], median_residual_norm=26.78
                )
                source = "mock"
            elif args.command == "eval" and args.tiny:
                from nous.model.tiny_backend import TinyBackend

                backend = TinyBackend(seed=args.seed)
                library = ConceptLibrary.load(args.library)
                source = "tiny"
            else:
                library = (
                    ConceptLibrary.load(args.library) if args.command != "build-library" else None
                )
                backend = HFBackend(local_path=str(args.model_path) if args.model_path else None)
                source = "realmodel"
            if args.command == "build-library":
                build_library(
                    backend,
                    load_concepts(),
                    seed=args.seed,
                    samples=args.samples,
                    neutral_samples=args.neutral_generations,
                    variant=args.variant,
                    median_norm=args.median_norm,
                    model_id=os.getenv("NOUS_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
                ).save(args.output)
            elif args.command == "eval":
                report = evaluate(
                    backend,
                    library,
                    alphas=args.alphas,
                    seeds=args.seeds,
                    prompts=args.prompts,
                    concepts=args.concepts,
                    held_out=args.held_out,
                    seed=args.seed,
                    source=source,
                )
                write_report(report, args.output)
                log.info("Evaluation saved to %s", args.output)
            elif args.command == "calibrate-alarm":
                calibrate_alarm(backend, library, count=args.generations, seed=args.seed)
                library.save(args.output or args.library)
            else:
                from nous.evaluation_data import load_calibration, load_examples, save_examples

                calibration = []
                if args.data:
                    calibration = load_calibration(args.data, library)
                    partitions = load_examples(args.data, library)
                else:
                    partitions = generate_training(backend, library, calibration=calibration)
                    destination = (args.output or args.library).parent / "readout-training.npz"
                    save_examples(destination, partitions, library, calibration=calibration)
                import hashlib

                dataset_path = args.data or destination
                library.provenance["readout_dataset_hash"] = hashlib.sha256(
                    dataset_path.read_bytes()
                ).hexdigest()
                report = fit_readout(library, *partitions, seed=args.seed, calibration=calibration)
                if not calibration:
                    log.warning("No idle calibration in this corpus; regenerate without --data")
                library.save(args.output or args.library)
                import json

                (args.output or args.library).with_suffix(".fit.json").write_text(
                    json.dumps(report, indent=2) + "\n"
                )
            return
        except (OSError, ValueError, ImportError) as exc:
            parser.exit(1, f"Offline evaluation unavailable: {exc}\n")
    if args.command == "start" or (
        args.command == "demo" and not args.mock and not args.script and not args.record
    ):
        from nous.server.experience import serve

        serve(args, welcome=args.command == "start")
        return
    client_id = os.getenv("NOUS_TWITCH_CLIENT_ID", "")
    if args.command in {"auth", "run"} and not client_id:
        parser.error("Set NOUS_TWITCH_CLIENT_ID to your Public app's client ID")
    if args.command == "auth":
        from nous.twitch.auth import AuthError, OAuth, TokenStore

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
        from nous.twitch.auth import AuthError, TokenStore

        if not re.fullmatch(r"[a-zA-Z0-9_]{1,25}", args.channel):
            parser.error("Use the channel login name without a URL or #")
        try:
            TokenStore().load()
        except AuthError as exc:
            parser.error(str(exc))
    from nous.server.leaderboard import Leaderboard

    leaderboard = Leaderboard(
        Path(os.getenv("NOUS_DATA_DIR", str(Path.home() / ".config" / "nous")))
        / "leaderboard.json",
        stream_id=os.getenv("NOUS_STREAM_ID"),
    )
    token = secrets.token_urlsafe(32)
    log.info("Local control token for this run: %s", token)
    if args.command == "demo":
        backend = MockBackend()
        if not args.mock:
            try:
                from nous.model.tiny_backend import TinyBackend

                backend = TinyBackend()
            except ImportError:
                log.info("Optional model dependencies absent; using the offline mock")
        crowd = Crowd(load_script(args.script), users=args.users)
        session = Session(
            backend=backend,
            crowd=crowd,
            leaderboard=leaderboard,
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
            start_round=session.start_round,
            leaderboard=session.scoring.board,
            control_token=token,
        )
    elif args.command == "run":
        from nous.twitch.live import LiveSession

        backend = MockBackend()
        library = mock_library(all_concepts=True)
        if not args.mock:
            from nous.model.hf_backend import HFBackend

            try:
                library = ConceptLibrary.load(args.library)
                backend = HFBackend(local_path=str(args.model_path))
            except (OSError, ValueError, ImportError) as exc:
                parser.exit(
                    1,
                    f"Local AI unavailable: {exc}\n"
                    "Run setup.bat on Windows, or install nous[model] and run "
                    "python -m nous.install. The recorded demo is available with nous demo.\n",
                )
        crowd = Crowd(twitch_connected=True, explicit_sim=args.sim)
        session = Session(
            backend=backend,
            library=library,
            crowd=crowd,
            source="LIVE",
            leaderboard=leaderboard,
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
            start_round=session.start_round,
            leaderboard=session.scoring.board,
        )
    else:
        player = Player(args.file)
        if not args.frames and any(
            row.get("event", {}).get("kind") == "round" and row["event"].get("phase") == "catalog"
            for row in player.rows
        ):
            parser.error("This recording changes topics. Replay it with --frames.")
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
                from nous.model.tiny_backend import TinyBackend

                replay_backend = TinyBackend(seed=player.metadata.get("backend_seed", 0))
            elif slug != "mock":
                from nous.model.hf_backend import HFBackend

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
        log.info("NOUS overlay: %s", url)
        log.info("Static screenshot fixture: %sfixture.html", url)
        log.info("Broadcaster controls: %scontrol", url)
        if not args.no_browser:
            webbrowser.open(url)

    app.on_startup.append(startup)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
