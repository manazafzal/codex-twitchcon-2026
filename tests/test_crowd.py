import asyncio
from importlib.resources import files
from pathlib import Path

from nous.sim.crowd import Crowd, load_script


def test_seeded_script_waves_and_names():
    script = {
        "seed": 7,
        "users": 3,
        "interval": 0.5,
        "waves": [
            {"duration": 10, "weights": {"ocean": 1}},
            {"duration": 10, "weights": {"space": 1}},
        ],
    }
    a, b = Crowd(script), Crowd(script)
    for i in range(40):
        first, second = a.push_at(i, i), b.push_at(i, i)
        assert first == second
        assert first.faction == ("ocean" if i % 20 < 10 else "space")
        assert first.user.startswith("sim_") and first.source == "SIMULATED"
    assert a.badge.label == "SIMULATED ×3"
    assert not Crowd(twitch_connected=True).enabled
    assert Crowd(twitch_connected=True, explicit_sim=True).enabled

    async def disabled():
        return [event async for event in Crowd(twitch_connected=True).stream()]

    assert asyncio.run(disabled()) == []


def test_committed_script_is_packaged():
    root = Path(__file__).resolve().parents[1]
    assert load_script(root / "golden/demo_script.json") == load_script()
    assert files("nous.sim").joinpath("demo_script.json").is_file()
