import argparse
import json
from pathlib import Path

from thoughtquake.concepts.builder import build_library
from thoughtquake.concepts.library import load_concepts
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import Mixer
from thoughtquake.model.mock_backend import MockBackend


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="THOUGHTQUAKE thought injection engine (M1)")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Emit offline engine events: TINY MODEL / CI")
    demo.add_argument("--mock", action="store_true", help="Use the deterministic offline backend")
    commands.add_parser("eval", help="Reserved for the evaluation milestone")
    build = commands.add_parser(
        "build-library", help="Generate a concept library with the local model"
    )
    build.add_argument("--output", type=Path, default=Path("library/qwen2.5-0.5b-instruct.npz"))
    args = parser.parse_args(argv)
    if args.command == "eval":
        parser.exit(
            2, "The evaluation harness is outside M1; no quality results have been produced.\n"
        )
    if args.command == "build-library":
        from thoughtquake.model.hf_backend import HFBackend

        backend = HFBackend()
        build_library(backend, load_concepts(), model_id=backend.model.config._name_or_path).save(
            args.output
        )
        return
    backend = MockBackend()
    library = build_library(backend, load_concepts()[:3], samples=1, neutral_samples=2)
    engine = Generator(backend, library, Mixer(), simulated_users=0)
    for event in engine.events():
        print(json.dumps(event.to_dict()))


if __name__ == "__main__":
    main()
