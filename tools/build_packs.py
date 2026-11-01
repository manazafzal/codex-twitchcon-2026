"""Publish explicit reports for every requested pack entry, including unavailable checks."""

import argparse
from pathlib import Path

from nous.concepts.library import ConceptLibrary, config_hash
from nous.concepts.topics import BuildResult, TopicBuilder, save_result, unavailable, write_json
from nous.config import library_path, model_dir

PACKS = {
    "cosmos": ["aurora", "comet", "nebula", "eclipse", "telescope", "orbit", "galaxy", "meteor"],
    "kitchen": ["soup", "baking", "spice", "knife", "oven", "pasta", "coffee", "grill"],
    "mythic": ["labyrinth", "phoenix", "oracle", "titan", "siren", "griffin", "trident", "legend"],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test the requested topic packs with local weights"
    )
    parser.add_argument("--library", type=Path, default=library_path())
    parser.add_argument("--model-path", type=Path, default=model_dir())
    parser.add_argument("--output", type=Path, default=Path("data/packs"))
    args = parser.parse_args()
    builder = None
    try:
        from nous.model.hf_backend import HFBackend

        library = ConceptLibrary.load(args.library)
        backend = HFBackend(local_path=str(args.model_path))
        builder = TopicBuilder(backend, library)
    except (OSError, ValueError, ImportError):
        pass
    for pack, names in PACKS.items():
        entries = []
        # Each pack starts from the same base; accepted entries extend only their own pack.
        current = builder
        for name in names:
            result = (
                current.build(name)
                if current
                else BuildResult(
                    unavailable(
                        name, "Local trained weights and a verified base library are unavailable"
                    )
                )
            )
            result.report["pack"] = pack
            save_result(result, args.output / pack / name)
            entries.append(
                {
                    "name": name,
                    "status": result.report["status"],
                    "report": f"{name}/quality.json",
                    "quality_hash": result.report["report_hash"],
                }
            )
            if result.library is not None:
                current = TopicBuilder(current.backend, result.library) if current else None
        manifest = {"name": pack, "seed": 0, "concepts": entries}
        manifest["pack_hash"] = config_hash(manifest)
        write_json(args.output / pack / "pack.json", manifest)


if __name__ == "__main__":
    main()
