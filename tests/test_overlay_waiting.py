import asyncio
import json

import pytest

from nous.engine.events import Badge, Mode, Push, Round, Tick, Token
from nous.server.state import ViewState
from tools.overlay_browser import CHROME, Browser

pytestmark = pytest.mark.skipif(not CHROME, reason="Local Chrome is not installed")


async def dispatch(browser, event):
    await browser.evaluate(f"NousOverlay.dispatch({json.dumps(event.to_dict())})")


async def waiting(browser):
    return await browser.evaluate("document.body.classList.contains('waiting')")


async def visible(browser, selector):
    return await browser.evaluate(
        f"[...document.querySelectorAll({json.dumps(selector)})].every(n=>n.getClientRects().length>0)"
    )


def test_idle_rounds_stay_calm_and_restore_after_snapshot(monkeypatch):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        async with Browser("manual&scale=.5&nogl") as browser:
            await browser.evaluate("NousOverlay.fixture.pause();NousOverlay.reset()")
            assert await waiting(browser)
            assert not await visible(browser, "#pushes")
            await dispatch(browser, Badge("LIVE"))
            # The real server starts background answers even with no participants.
            await dispatch(browser, Round("war", "start", 0, ""))
            await dispatch(browser, Mode("war", False, "Explain how to make tea.", 0))
            await dispatch(browser, Tick({"Neutral": 1}, 0, [], 0))
            await dispatch(
                browser,
                Token(0, "Warm the cup. ", None, {"scores": {}, "top": None, "margin": 0}, None),
            )
            await browser.evaluate("NousOverlay.step(1)")
            assert await waiting(browser)
            assert await browser.evaluate("document.getElementById('mode').textContent==='WAITING'")
            assert await browser.evaluate(
                "document.getElementById('round-headline').textContent==='Waiting for chat. Type !join to play.'"
            )
            for selector in (
                "#colour-label",
                "#mind-share",
                "#countdown",
                "#mode-caption",
                "#pushes",
            ):
                assert not await visible(browser, selector)
            assert await browser.evaluate(
                "document.getElementById('answer').textContent==='Warm the cup. '"
            )
            assert await browser.evaluate(
                "document.getElementById('ai-guess').textContent==='No clear thought yet'"
            )
            assert await visible(browser, "#source")
            await dispatch(browser, Push("Mum", "ocean", 1, "LIVE"))
            assert await visible(browser, "#pushes")
            # Participation becomes active when represented in a round's Mind Share.
            await dispatch(browser, Tick({"ocean": 0.75, "Neutral": 0.25}, 1, [], 1))
            assert not await waiting(browser)
            assert await visible(browser, "#colour-label,#mind-share,#countdown")
            assert await browser.evaluate(
                "document.getElementById('mode').textContent==='TEAM ROUND'"
            )
            assert await browser.evaluate(
                "document.getElementById('round-headline').textContent.toLowerCase().includes('ocean')"
            )
            # A neutral snapshot clears the old participant feed and old team state.
            await dispatch(browser, ViewState().snapshot())
            await browser.evaluate("NousOverlay.step(.5)")
            assert await waiting(browser)
            assert not await visible(browser, "#pushes")
            assert not await visible(browser, "#mind-share")
            # A fresh team round snapshot restores participation, not the waiting UI.
            state = ViewState()
            state.apply(Tick({"ocean": 0.75, "Neutral": 0.25}, 1, [], 2))
            state.apply(Mode("war", False, "Pack a bag.", 2))
            await dispatch(browser, state.snapshot())
            assert not await waiting(browser)
            assert await visible(browser, "#mind-share")
            await browser.evaluate("NousOverlay.reset()")
            await dispatch(browser, Tick({"ocean": 0.75, "Neutral": 0.25}, 1, [], 3))
            assert await waiting(browser)
            await dispatch(browser, Mode("war", False, "Pack a bag.", 3))
            assert not await waiting(browser)
            assert not browser.errors

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["attack", "telepathy"])
def test_explicit_challenges_are_active_without_public_pushes(monkeypatch, mode):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        async with Browser("manual&scale=.5&nogl") as browser:
            await browser.evaluate("NousOverlay.fixture.pause();NousOverlay.reset()")
            await dispatch(browser, Tick({"Neutral": 1}, 0, [], 0))
            await dispatch(browser, Mode(mode, False, "Make tea.", 1, phase="armed", remaining=10))
            assert not await waiting(browser)
            assert await visible(browser, "#countdown")
            if mode == "telepathy":
                assert await browser.evaluate(
                    "document.getElementById('round-headline').textContent.includes('???')"
                )
                assert await browser.evaluate(
                    "document.getElementById('ai-guess').textContent==='Hidden until the reveal'"
                )
            await browser.evaluate("NousOverlay.step(1)")
            assert await browser.evaluate(
                "document.getElementById('countdown').textContent==='9s left'"
            )
            assert not browser.errors

    asyncio.run(run())


@pytest.mark.parametrize("size", [(1920, 1080), (480, 270)])
def test_entire_current_answer_fits_during_stream_and_new_answer_resets_size(monkeypatch, size):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")
    lines = [
        "**First, warm the cup** and set out everything you need.",
        "Choose a quiet spot, then put fresh water in the kettle.",
        "While it heats, arrange the cups and a small plate of biscuits.",
        "Add the tea, pour the water gently, and wait a little.",
        "Take out the leaves, add milk if you like, and stir slowly.",
        "Carry the tray carefully and enjoy the last warm sip together.",
    ]

    async def run():
        async with Browser("manual&scale=.5&nogl", *size) as browser:
            await browser.evaluate("NousOverlay.fixture.pause();NousOverlay.reset()")
            await dispatch(browser, Mode("war", False, "Explain how to make tea.", 1))
            for i, line in enumerate(lines):
                await dispatch(
                    browser,
                    Token(i, line + "\n", None, {"scores": {}, "top": None, "margin": 0}, None),
                )
                await browser.evaluate("NousOverlay.step(1)")
                metrics = await browser.evaluate("""(()=>{const a=document.getElementById('answer');return {
                    fits:a.scrollHeight<=a.clientHeight&&a.scrollWidth<=a.clientWidth,
                    scroll:a.scrollTop,mask:getComputedStyle(a).maskImage,
                    allVisible:[...a.querySelectorAll('span')].every(n=>getComputedStyle(n).visibility==='visible'),
                    size:parseFloat(getComputedStyle(a).fontSize)};})()""")
                assert metrics["fits"] and metrics["allVisible"]
                assert metrics["scroll"] == 0 and metrics["mask"] == "none"
                assert metrics["size"] >= 17
            assert 17 <= metrics["size"] < 56
            assert await browser.evaluate(
                "document.getElementById('answer').textContent.startsWith('First, warm the cup')"
            )
            assert await browser.evaluate(
                "document.getElementById('answer').textContent.endsWith('last warm sip together.\\n')"
            )
            # Verify line breaks survive in history and the excerpt ends on a whole line.
            await dispatch(browser, Mode("war", False, "Pack a bag.", 2))
            assert await browser.evaluate(
                "parseFloat(getComputedStyle(document.getElementById('answer')).fontSize)===56"
            )
            await dispatch(
                browser,
                Token(
                    0, "Pack a light bag. ", None, {"scores": {}, "top": None, "margin": 0}, None
                ),
            )
            await browser.evaluate("NousOverlay.step(1)")
            history = await browser.evaluate("""(()=>{const card=document.querySelector('#history article'),body=card.querySelector('div'),css=getComputedStyle(body);return {
                text:body.textContent,whiteSpace:css.whiteSpace,clamp:css.webkitLineClamp,
                lines:body.getBoundingClientRect().height/(innerWidth/1920)/parseFloat(css.lineHeight),
                cardFits:card.scrollHeight<=card.clientHeight};})()""")
            assert history["text"].count("\n") == len(lines)
            assert history["whiteSpace"] == "pre-wrap" and history["clamp"] == "3"
            assert history["lines"] == pytest.approx(3, abs=0.03)
            assert history["cardFits"]
            assert not browser.errors

    asyncio.run(run())
