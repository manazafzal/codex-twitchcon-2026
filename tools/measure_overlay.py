"""Capture five scenes and report measured software-renderer frame intervals."""

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

import numpy as np

from tools.overlay_browser import CHROME, Browser, fixture_environment, pixels

SCENES = ("war", "attack", "immune", "telepathy", "reveal")
SCENE_TIMES = {"attack": 3.5, "reveal": 8.5}


async def advance(browser, seconds):
    await browser.evaluate(f"""(()=>{{const atlas=ThoughtquakeAtlas,draw=atlas.draw;
        atlas.draw=()=>{{}};try{{for(let i=0;i<{round(seconds * 30)};i++)
        ThoughtquakeOverlay.step(1/30);}}finally{{atlas.draw=draw;}}atlas.draw();}})()""")


async def measure(output):
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    for scene in SCENES:
        async with Browser(f"manual&scale=.5&scene={scene}") as browser:
            await advance(browser, SCENE_TIMES.get(scene, 10))
            png = await browser.screenshot()
            (output / f"{scene}.png").write_bytes(png)
            image = pixels(png)
            results[scene] = {
                "renderer": await browser.evaluate("ThoughtquakeAtlas.renderer"),
                "white_fraction": float(np.all(image[:, :, :3] >= 250, axis=2).mean()),
                "console_errors": len(browser.errors),
            }
    async with Browser("scale=.5&scene=war") as browser:
        # Measure actual rAF intervals, without screenshots or CDP per-frame traffic.
        start = time.perf_counter()
        timing = await browser.evaluate(
            """new Promise(resolve=>{const samples=[];let last;
            function next(t){if(last!=null)samples.push(t-last);last=t;
                if(samples.length<120)requestAnimationFrame(next);else resolve(samples);}
            requestAnimationFrame(next);})""",
            await_promise=True,
        )
        results["performance"] = {
            "frames": len(timing),
            "mean_ms": float(np.mean(timing)),
            "fps": 1000 / float(np.mean(timing)),
            "p95_ms": float(np.percentile(timing, 95)),
            "wall_seconds": time.perf_counter() - start,
            "stats": await browser.evaluate("ThoughtquakeOverlay.stats()"),
        }
    async with Browser("manual&scale=.5&bg=transparent") as browser:
        await advance(browser, 10)
        png = await browser.screenshot()
        (output / "transparent.png").write_bytes(png)
        results["transparent"] = {
            "fraction_alpha_below_255": float((pixels(png)[:, :, 3] < 255).mean())
        }
    async with Browser("manual&scale=.5", 480, 270) as browser:
        await advance(browser, 10)
        png = await browser.screenshot()
        (output / "quarter.png").write_bytes(png)
        patch = pixels(png)[60:164, 24:219, :3] / 255
        linear = np.where(patch <= 0.04045, patch / 12.92, ((patch + 0.055) / 1.055) ** 2.4)
        luminance = linear @ np.array([0.2126, 0.7152, 0.0722])
        results["quarter"] = {
            "left_column_contrast_ratio": float(
                (np.percentile(luminance, 99) + 0.05) / (np.percentile(luminance, 20) + 0.05)
            )
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    fixture_environment()
    results = asyncio.run(measure(args.output))
    Path("docs/overlay-measurements.json").write_text(json.dumps(results, indent=2) + "\n")
    perf = results["performance"]
    chrome = subprocess.check_output([CHROME, "--version"], text=True).strip()
    rows = "\n".join(
        f"| {scene} | {results[scene]['renderer']} | {results[scene]['white_fraction'] * 100:.4f}% | {results[scene]['console_errors']} |"
        for scene in SCENES
    )
    film_file = Path("docs/film-hashes.json")
    film_note = "Film hash report is not present."
    if film_file.exists():
        evidence = json.loads(film_file.read_text())
        film_note = (
            f"Two fresh Chrome runs each captured {evidence['frames']} lossless frames over "
            f"{evidence['seconds']} virtual seconds at {evidence['fps']} output fps. "
            f"Every PNG hash matched: **{evidence['identical']}**. Sequence SHA-256: "
            f"`{evidence['sequence_sha256']}`. [Full frame hashes](film-hashes.json)."
        )
    Path("docs/perf.md").write_text(f"""# Mind Atlas performance and visual checks

Measured with **{chrome}**, headless Linux, CPU SwiftShader, `?scale=.5`. The field buffer is 960×540, the effects layer is 1920×1080, and the stage is 1920×1080. Chrome uses `--use-angle=swiftshader --enable-unsafe-swiftshader`; all page assets are local. The measured scene uses explicitly labelled mock traces, not trained-model evidence.

## Playback timing

{perf["frames"]} actual requestAnimationFrame intervals, sampled without per-frame screenshots or DevTools commands:

| Mean frame | Measured playback | 95th percentile |
| --- | --- | --- |
| {perf["mean_ms"]:.2f} ms | {perf["fps"]:.2f} fps | {perf["p95_ms"]:.2f} ms |

This software renderer is CPU-bound. **Hardware-GPU 60 fps is unverified.** The 30 fps film cadence is a virtual output rate and is not a playback-speed claim. The scale governor reduces resolution by .125 after a 60-frame mean above 22 ms, stopping at .5; this measurement starts at that minimum. Canvas-only rendering is available with `?nogl`.

## Screenshots and pixel checks

Five scenes captured at 1920×1080. The brightness limit is 0.5% of pixels with every RGB channel at least 250.

| Scene | Renderer | Bright pixels | Console errors |
| --- | --- | --- | --- |
{rows}

Transparent capture: **{results["transparent"]["fraction_alpha_below_255"] * 100:.2f}%** of pixels have alpha below 255 (minimum 90%). Quarter-size left-column contrast: **{results["quarter"]["left_column_contrast_ratio"]:.2f}:1** (minimum 4.5:1). Contrast compares the 99th-percentile glyph-interior luminance with the 20th-percentile adjacent ground in the left answer region; antialiased boundaries are excluded. This is a raster region check, not a guarantee for arbitrary OBS footage.

Browser tests also verify every canvas has an accessible label, computed text sizes are at least 17 stage pixels, and full Mind Share and ridge labels fit without overflow. Long-name coverage includes Time Travel. Five screenshots plus [transparent](screenshots/transparent.png) and [quarter-size](screenshots/quarter.png) captures are in [screenshots/](screenshots/).

## Deterministic film

{film_note}

## Reproduce

```sh
make check
python -m tools.measure_overlay
python -m tools.film --verify --output /tmp/thoughtquake.mp4
```

The scripts enable development fixtures only within their process. To view them separately: `THOUGHTQUAKE_DEV_FIXTURES=1 thoughtquake demo --mock`, then open `/fixture.html?scene=war` (also attack, immune, telepathy, reveal). Use `backend=tiny` for captured random-init model states and text. No test downloads a browser, font, model or JavaScript dependency.

Not verified: trained-model visuals, hardware GPU performance, OBS composition over actual stream footage, and live Twitch viewing. The requested milestone geometry and 17 px minimum supersede SPEC §15's previous layout and type minimum.
""")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
