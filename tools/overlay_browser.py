"""Small Chrome DevTools client; no browser framework or runtime downloads."""

import asyncio
import base64
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import aiohttp
import numpy as np
from aiohttp.test_utils import TestServer

from nous.server.app import create_app

CHROME = shutil.which("chromium") or shutil.which("google-chrome")


class Browser:
    def __init__(
        self,
        query="manual&scale=.5",
        width=1920,
        height=1080,
        *,
        app_factory=create_app,
        path="/fixture.html",
    ):
        self.app_factory, self.path = app_factory, path
        self.query, self.width, self.height = query, width, height
        self.errors = []
        self.counter = 0

    async def __aenter__(self):
        if not CHROME:
            raise RuntimeError("Chrome is unavailable")
        self.temp = tempfile.TemporaryDirectory(prefix="nous-chrome-", ignore_cleanup_errors=True)
        self.server = TestServer(self.app_factory())
        await self.server.start_server()
        self.process = await asyncio.to_thread(
            subprocess.Popen,
            [
                CHROME,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-proxy-server",
                "--disable-sync",
                "--metrics-recording-only",
                "--disable-domain-reliability",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--disable-gpu-sandbox",
                "--disable-lcd-text",
                "--font-render-hinting=none",
                "--force-color-profile=srgb",
                "--hide-scrollbars",
                "--run-all-compositor-stages-before-draw",
                "--disable-threaded-animation",
                "--disable-threaded-scrolling",
                "--disable-features=PaintHolding,MediaRouter,OptimizationHints",
                "--remote-debugging-port=0",
                f"--user-data-dir={self.temp.name}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        portfile = Path(self.temp.name) / "DevToolsActivePort"
        for _ in range(200):
            if portfile.exists():
                break
            if self.process.poll() is not None:
                raise RuntimeError("Chrome exited during startup")
            await asyncio.sleep(0.05)
        port = portfile.read_text().splitlines()[0]
        self.http = aiohttp.ClientSession()
        async with self.http.get(f"http://127.0.0.1:{port}/json/list") as response:
            targets = await response.json()
        self.ws = await self.http.ws_connect(targets[0]["webSocketDebuggerUrl"])
        await self.call("Runtime.enable")
        await self.call("Log.enable")
        await self.call("Page.enable")
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=self.width,
            height=self.height,
            deviceScaleFactor=1,
            mobile=False,
        )
        await self.call(
            "Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0}
        )
        url = str(self.server.make_url(self.path).with_query(self.query))
        await self.call("Page.navigate", url=url)
        for _ in range(200):
            condition = (
                "!!window.NOUS_WELCOME_READY"
                if self.path.startswith("/welcome")
                else "!!window.NousOverlay?.fixture"
            )
            if await self.evaluate(condition):
                break
            await asyncio.sleep(0.025)
        else:
            state = await self.evaluate(
                "({url:location.href,body:document.body?.textContent,scripts:Array.from(document.scripts).map(s=>s.src),ui:!!window.NousOverlay,trace:!!window.NOUS_TRACES})"
            )
            await self.__aexit__()
            raise RuntimeError(f"Fixture did not start: {self.errors} {state}")
        await self.evaluate(
            "Promise.all([document.fonts.load('56px Cormorant'),document.fonts.load('20px Plex')]).then(()=>true)",
            await_promise=True,
        )
        return self

    async def call(self, method, **params):
        self.counter += 1
        request_id = self.counter
        await self.ws.send_json({"id": request_id, "method": method, "params": params})
        while True:
            message = await self.ws.receive_json()
            if (
                message.get("method") == "Log.entryAdded"
                and message["params"]["entry"]["level"] == "error"
            ):
                self.errors.append(message["params"]["entry"])
            if message.get("method") == "Runtime.exceptionThrown":
                self.errors.append(message["params"]["exceptionDetails"])
            if (
                message.get("method") == "Runtime.consoleAPICalled"
                and message["params"]["type"] == "error"
            ):
                self.errors.append(message["params"])
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    async def evaluate(self, expression, await_promise=False):
        result = await self.call(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=await_promise,
        )
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    async def screenshot(self):
        result = await self.call(
            "Page.captureScreenshot", format="png", captureBeyondViewport=False
        )
        return base64.b64decode(result["data"])

    async def __aexit__(self, *args):
        await self.ws.close()
        await self.http.close()
        self.process.terminate()
        await asyncio.to_thread(self.process.wait)
        self.temp.cleanup()
        await self.server.close()


def pixels(png):
    """Decode Chrome's lossless RGB/RGBA PNGs using only the standard library."""
    offset, compressed = 8, bytearray()
    while offset < len(png):
        size = struct.unpack(">I", png[offset : offset + 4])[0]
        kind, data = png[offset + 4 : offset + 8], png[offset + 8 : offset + 8 + size]
        if kind == b"IHDR":
            width, height, bits, color, _, _, interlace = struct.unpack(">IIBBBBB", data)
            assert bits == 8 and color in (2, 6) and interlace == 0
        if kind == b"IDAT":
            compressed.extend(data)
        offset += size + 12
    channels = 4 if color == 6 else 3
    raw, stride = zlib.decompress(compressed), width * channels
    image = np.zeros((height, stride), dtype=np.uint8)
    for y in range(height):
        filter_type = raw[y * (stride + 1)]
        row = np.frombuffer(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)], dtype=np.uint8)
        if filter_type == 0:
            image[y] = row
        elif filter_type == 2:
            image[y] = row + (image[y - 1] if y else 0)
        else:
            for x, value in enumerate(row):
                a = int(image[y, x - channels]) if x >= channels else 0
                b = int(image[y - 1, x]) if y else 0
                c = int(image[y - 1, x - channels]) if y and x >= channels else 0
                if filter_type == 1:
                    predictor = a
                elif filter_type == 3:
                    predictor = (a + b) // 2
                else:
                    p = a + b - c
                    distances = (abs(p - a), abs(p - b), abs(p - c))
                    predictor = (a, b, c)[distances.index(min(distances))]
                image[y, x] = (int(value) + predictor) % 256
    image = image.reshape(height, width, channels)
    if channels == 3:
        image = np.concatenate([image, np.full((height, width, 1), 255, dtype=np.uint8)], axis=2)
    return image


def fixture_environment():
    os.environ["NOUS_DEV_FIXTURES"] = "1"
