"""Film twenty virtual seconds at thirty frames/s, optionally encoding an MP4."""

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from tools.overlay_browser import Browser, fixture_environment


async def film(*, seconds=20, fps=30, output=None, scene="war", backend="mock", size=(1920, 1080)):
    hashes = []
    encoder = None
    if output:
        encoder = await asyncio.to_thread(
            subprocess.Popen,
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "image2pipe",
                "-framerate",
                str(fps),
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output),
            ],
            stdin=subprocess.PIPE,
        )
    try:
        async with Browser(f"manual&scale=.5&scene={scene}&backend={backend}", *size) as browser:
            for _ in range(round(seconds * fps)):
                await browser.evaluate(f"window.ThoughtquakeOverlay.step({1 / fps!r})")
                frame = await browser.screenshot()
                hashes.append(hashlib.sha256(frame).hexdigest())
                if encoder:
                    await asyncio.to_thread(encoder.stdin.write, frame)
            assert not browser.errors, browser.errors
    finally:
        if encoder:
            encoder.stdin.close()
            code = await asyncio.to_thread(encoder.wait)
            if code:
                raise RuntimeError(f"Video encoder exited with {code}")
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hashes", type=Path, default=Path("/tmp/thoughtquake-film.json"))
    parser.add_argument(
        "--scene", choices=["war", "attack", "immune", "telepathy", "reveal"], default="war"
    )
    parser.add_argument("--backend", choices=["mock", "tiny"], default="mock")
    parser.add_argument("--verify", action="store_true", help="Compare all 600 frame hashes twice")
    args = parser.parse_args()
    fixture_environment()
    hashes = asyncio.run(film(output=args.output, scene=args.scene, backend=args.backend))
    if args.verify:
        again = asyncio.run(film(scene=args.scene, backend=args.backend))
        assert hashes == again, "Film hashes differ"
    args.hashes.write_text(
        json.dumps(
            {"seconds": 20, "fps": 30, "hashes": hashes, "verified_twice": args.verify}, indent=2
        )
        + "\n"
    )
    print(f"{len(hashes)} frames; hash list: {args.hashes}; identical twice: {args.verify}")


if __name__ == "__main__":
    main()
