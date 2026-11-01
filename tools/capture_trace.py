"""Record actual backend states for development scenes, with explicit provenance."""

import json
from dataclasses import asdict, replace
from pathlib import Path

from thoughtquake.concepts.builder import build_library
from thoughtquake.concepts.library import load_concepts
from thoughtquake.engine.events import Badge, Layout, Mode, Push, Token
from thoughtquake.engine.generate import Generator
from thoughtquake.engine.mixer import FakeClock, Mixer
from thoughtquake.engine.rounds import FixedInjection
from thoughtquake.model.mock_backend import MockBackend
from thoughtquake.model.tiny_backend import TinyBackend
from thoughtquake.server.presentation import Presentation
from thoughtquake.server.session import mock_library
from thoughtquake.server.state import ViewState


def capture(backend, library):
    scenes = {}
    for name in ("war", "attack", "immune", "telepathy", "reveal"):
        clock = FakeClock()
        mixer = Mixer(clock=clock)
        for i in range(40):
            mixer.push(Push(f"sim_{i:03}", library.ids[i % 3], 0, "SIMULATED"))
        engine = Generator(backend, library, mixer, seed=42, clock=clock, simulated_users=40)
        state = ViewState(library.concepts)
        for event in engine.events(answers=3, max_tokens=24):
            state.apply(event)
        frames = [
            state.snapshot(),
            Badge("SIMULATED ×40", "TINY MODEL / CI", 40),
            Layout(engine.atlas.points),
        ]
        frames.extend(Push(f"sim_{i:03}", library.ids[i % 3], 0, "SIMULATED") for i in range(5))
        panels = ("off", "on") if name in ("attack", "immune") else ("main",)
        for panel in panels:
            if name != "war":
                engine.mixer = FixedInjection(mixer, library.ids[0])
            engine.immune = panel == "on"
            for event in engine.events(max_tokens=36):
                if isinstance(event, Badge):
                    continue
                if isinstance(event, Mode):
                    event = replace(
                        event,
                        mode="telepathy"
                        if name in ("telepathy", "reveal")
                        else "attack"
                        if name in ("attack", "immune")
                        else "war",
                        panel=panel,
                        round_id=1,
                        candidates=tuple(library.ids[:3]),
                    )
                frames.append(event)
        if name == "reveal":
            frames.append(
                Mode(
                    "telepathy",
                    False,
                    "Explain how to make tea.",
                    0,
                    phase="reveal",
                    reveal=library.ids[0],
                    round_id=1,
                )
            )
        public = Presentation()
        result = []
        for event in frames:
            result.append(public.event(event).to_dict())
            if isinstance(event, Mode) and public.points:
                result.append(public.layout().to_dict())
        assert any(isinstance(e, Token) for e in frames)
        scenes[name] = result
    return scenes


def main():
    import torch

    torch.set_num_threads(1)
    tiny = TinyBackend(seed=42)
    library = build_library(tiny, load_concepts(), samples=2, neutral_samples=12, seed=42)
    data = {
        "provenance": {
            "tiny": "Recorded random-init TinyBackend, seed 42; not trained-model evidence.",
            "mock": "Recorded deterministic numpy MockBackend; not model-quality evidence.",
        },
        "tiny": capture(tiny, library),
        "mock": capture(MockBackend(), mock_library()),
        "concepts": [asdict(c) for c in library.concepts],
    }
    Path("src/thoughtquake/overlay/trace_data.js").write_text(
        "/* Recorded development traces; never production data. */\nwindow.THOUGHTQUAKE_TRACES = "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )


if __name__ == "__main__":
    main()
