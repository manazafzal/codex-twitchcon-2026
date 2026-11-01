import asyncio
import json
import re

import pytest

from nous.engine.events import Mode, Token
from nous.server.experience import Experience, make_experience_app
from tools.overlay_browser import CHROME, Browser

pytestmark = pytest.mark.skipif(not CHROME, reason="Local Chrome is not installed")


def test_default_labels_are_plain_and_nerd_panel_keeps_the_secret_hidden(monkeypatch):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        async with Browser("manual&scale=.5&nogl") as browser:
            assert not await browser.evaluate("document.getElementById('nerd').open")
            visible = await browser.evaluate(
                """(()=>{const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;const texts=[];while(node=walker.nextNode()){const r=document.createRange();r.selectNodeContents(node);if([...r.getClientRects()].some(b=>b.width&&b.height))texts.push(node.textContent);}return texts.join(' ');})()"""
            )
            assert not re.search(
                r"\balpha\b|\blayers?\b|z[- ]?scores?|immune thresholds?", visible, re.IGNORECASE
            )
            await browser.evaluate("NousOverlay.fixture.pause()")
            mode = Mode(
                "telepathy",
                False,
                "Make tea.",
                99,
                phase="armed",
                remaining=10,
                round_id=99,
                injection="cats",
            )
            await browser.evaluate(f"NousOverlay.dispatch({json.dumps(mode.to_dict())})")
            assert await browser.evaluate(
                "document.getElementById('round-headline').textContent.includes('???')"
            )
            await browser.evaluate("document.getElementById('nerd').open=true")
            token = Token(
                0, "A quiet cup. ", None, {"scores": {"cats": 9}, "top": "cats", "margin": 9}, None
            )
            await browser.evaluate(f"NousOverlay.dispatch({json.dumps(token.to_dict())})")
            assert await browser.evaluate(
                "document.getElementById('nerd-values').textContent==='Hidden until the reveal'"
            )
            assert not await browser.evaluate(
                "document.getElementById('nerd').textContent.toLowerCase().includes('cats')"
            )
            await browser.evaluate("NousOverlay.step(1)")
            assert await browser.evaluate(
                "document.getElementById('countdown').textContent==='9s left'"
            )
            guessing = Mode(
                "telepathy", False, "Make tea.", 99, phase="guessing", remaining=8, round_id=99
            )
            await browser.evaluate(f"NousOverlay.dispatch({json.dumps(guessing.to_dict())})")
            assert await browser.evaluate(
                "document.getElementById('round-headline').textContent==='Guess what the AI is thinking!'"
            )
            reveal = Mode(
                "telepathy",
                False,
                "Make tea.",
                99,
                phase="reveal",
                reveal="cats",
                winner="Mum",
                probe_top="cats",
            )
            await browser.evaluate(f"NousOverlay.dispatch({json.dumps(reveal.to_dict())})")
            assert await browser.evaluate("document.getElementById('reveal').hidden")
            await browser.evaluate("NousOverlay.step(1.41)")
            assert await browser.evaluate(
                "!document.getElementById('reveal').hidden&&document.getElementById('reveal').textContent==='CATS'"
            )
            assert await browser.evaluate(
                "document.getElementById('winner').textContent==='Mum guessed it!'"
            )
            assert await browser.evaluate(
                "document.getElementById('countdown').textContent==='Revealed!'"
            )
            assert not browser.errors

    asyncio.run(run())


def test_welcome_button_opens_an_offline_recording_in_a_real_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("NOUS_DEV_FIXTURES", raising=False)

    async def run():
        experience = Experience()
        async with Browser(
            "manual&scale=.5&nogl",
            app_factory=lambda: make_experience_app(token="test-run", experience=experience),
            path="/welcome.html#test-run",
        ) as browser:
            assert await browser.evaluate("location.hash===''")
            assert await browser.evaluate(
                "document.getElementById('try-demo').textContent==='Try the demo'"
            )
            assert not await browser.evaluate("document.cookie.includes('nous_control')")
            experience.client_id = "incorrect-code"
            experience.login = {
                "status": "error",
                "stage": "login",
                "message": "Check the app code and retry.",
            }
            await asyncio.sleep(1.3)
            assert await browser.evaluate("!document.getElementById('app-help').hidden")
            assert await browser.evaluate(
                "document.getElementById('login').textContent==='Try login again'"
            )
            await browser.evaluate("document.getElementById('try-demo').click()")
            for _ in range(200):
                if await browser.evaluate("!!window.NousOverlay"):
                    break
                await asyncio.sleep(0.025)
            assert await browser.evaluate("location.pathname==='/overlay/'")
            for _ in range(100):
                if await browser.evaluate(
                    "document.getElementById('quality').textContent.includes('RECORDING')"
                ):
                    break
                await asyncio.sleep(0.02)
            assert await browser.evaluate(
                "document.getElementById('quality').textContent.includes('RECORDING')"
            )
            assert await browser.evaluate(
                "document.getElementById('source').textContent==='SIMULATED ×40'"
            )
            assert not browser.errors

    asyncio.run(run())
