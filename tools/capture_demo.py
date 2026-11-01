"""Capture the shipped pretend-chat recording using actual local test-backend calls."""

import asyncio
import json
from pathlib import Path

from nous.engine.events import Badge, Guess, Mode, Push
from nous.engine.mixer import FakeClock
from nous.game.telepathy import Telepathy
from nous.server.session import Session, mock_library
from nous.sim.crowd import Crowd


async def capture():
    clock = FakeClock()
    seed = next(
        s
        for s in range(1000)
        if Telepathy(mock_library().concepts, seed=s).arm({"space", "jazz"}) == "ocean"
    )
    session = Session(clock=clock, seed=seed, crowd=Crowd(twitch_connected=True))
    session.telepathy.seconds = 10
    session.switch_mode("telepathy")
    for i in range(40):
        session.pending.put_nowait(
            Push(f"sim_{i + 1:03}", "space" if i % 2 else "jazz", 0, "SIMULATED")
        )
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        clock.advance(0.2 if seconds == 0.08 else seconds)
        await real_sleep(0)

    asyncio.sleep = sleep
    rows, guessed = [], False
    stream = session.events()
    try:
        async for event in stream:
            if isinstance(event, Badge):
                event = Badge("SIMULATED ×40", "RECORDING · Pretend chat · Test AI", 40)
            rows.append({"at": round(clock(), 6), "event": event.to_dict()})
            if (
                isinstance(event, Mode)
                and event.phase == "guessing"
                and not guessed
                and event.remaining <= 2
            ):
                session.pending.put_nowait(Guess("sim_001", "sea", clock(), "SIMULATED", "sim_001"))
                guessed = True
            if isinstance(event, Mode) and event.phase == "idle":
                break
    finally:
        await stream.aclose()
        asyncio.sleep = real_sleep
    return {
        "description": "Recorded MockBackend calls with scripted pretend chat. Not trained-model evidence. Logical time controls the presentation cadence, not model speed.",
        "seed": seed,
        "library_hash": session.library.hash,
        "duration": 24,
        "rows": rows,
    }


if __name__ == "__main__":
    Path("src/nous/sim/demo_round.json").write_text(
        json.dumps(asyncio.run(capture()), indent=2) + "\n"
    )
