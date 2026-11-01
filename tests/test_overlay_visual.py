import asyncio
import hashlib
import json

import numpy as np
import pytest

from tools.film import film
from tools.measure_overlay import SCENE_TIMES, SCENES, advance
from tools.overlay_browser import CHROME, Browser, pixels

pytestmark = pytest.mark.skipif(not CHROME, reason="Chrome is not installed; no downloads")


@pytest.mark.parametrize("scene", SCENES)
def test_scenes_console_labels_and_luminance(scene, monkeypatch):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        async with Browser(f"manual&scale=.5&scene={scene}") as browser:
            await advance(browser, SCENE_TIMES.get(scene, 10))
            image = pixels(await browser.screenshot())
            assert np.all(image[:, :, :3] >= 250, axis=2).mean() <= 0.005
            assert await browser.evaluate("document.getElementById('stage').dataset.renderer") in (
                "gl",
                "2d",
            )
            assert await browser.evaluate(
                "Array.from(document.querySelectorAll('canvas')).every(e=>e.getAttribute('aria-label'))"
            )
            assert await browser.evaluate(
                "Array.from(document.querySelectorAll('#share-legend span,.ridge-label')).every(e=>e.scrollWidth<=e.clientWidth)"
            )
            assert await browser.evaluate(
                "Array.from(document.querySelectorAll('body *')).filter(e=>e.childNodes.length&&[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).every(e=>parseFloat(getComputedStyle(e).fontSize)>=17)"
            )
            if scene == "telepathy":
                assert await browser.evaluate("document.body.classList.contains('blind')")
                assert await browser.evaluate(
                    "NousAtlas.stars.every(s=>!NousAtlas.catalog.has(s.id))"
                )
            if scene == "reveal":
                assert await browser.evaluate(
                    "NousAtlas.stars.every(s=>NousAtlas.catalog.has(s.id))"
                )
                assert not await browser.evaluate(
                    "/[a-f0-9]{16}/i.test(document.getElementById('share-legend').textContent)"
                )
            assert await browser.evaluate(
                "(()=>{const a=document.getElementById('history').getBoundingClientRect(),b=document.getElementById('sky-caption').getBoundingClientRect();return a.right<=b.left||a.left>=b.right||a.bottom<=b.top||a.top>=b.bottom;})()"
            )
            assert not browser.errors

    asyncio.run(run())


def test_transparency_fallback_and_contrast(monkeypatch):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        async with Browser("manual&scale=.5&bg=transparent") as browser:
            await advance(browser, 10)
            image = pixels(await browser.screenshot())
            assert (image[:, :, 3] < 255).mean() >= 0.9
            assert not browser.errors
        async with Browser("manual&scale=.5&nogl", 480, 270) as browser:
            await advance(browser, 10)
            assert await browser.evaluate("NousAtlas.renderer") == "2d"
            image = pixels(await browser.screenshot())[:, :, :3] / 255
            # Measure glyph interior pixels against the adjacent dark left-panel ground.
            # Anti-aliased edge pixels are excluded from foreground luminance.
            patch = image[60:164, 24:219]
            luminance = np.where(
                patch <= 0.04045, patch / 12.92, ((patch + 0.055) / 1.055) ** 2.4
            ) @ np.array([0.2126, 0.7152, 0.0722])
            foreground = np.percentile(luminance, 99)
            background = np.percentile(luminance, 20)
            assert (foreground + 0.05) / (background + 0.05) >= 4.5
            assert not browser.errors

    asyncio.run(run())


def test_full_twenty_second_film_hashes_repeat(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        first = await film()
        second = await film()
        assert len(first) == 600
        assert len(set(first)) > 300, "The signal-driven scene must evolve"
        (tmp_path / "film-hashes.json").write_text(
            json.dumps(
                {
                    "seconds": 20,
                    "fps": 30,
                    "frames": len(first),
                    "identical": first == second,
                    "sequence_sha256": hashlib.sha256("".join(first).encode()).hexdigest(),
                    "first": first,
                    "second": second,
                },
                indent=2,
            )
            + "\n"
        )
        assert first == second

    asyncio.run(run())


def test_virtual_timers_and_full_long_names(monkeypatch):
    monkeypatch.setenv("NOUS_DEV_FIXTURES", "1")

    async def run():
        async with Browser("manual&scale=.5&nogl", 480, 270) as browser:
            times = await browser.evaluate("""(()=>{const ui=NousOverlay, times=[];
                ui.later(()=>{times.push(ui.stats().time);ui.later(()=>times.push(ui.stats().time),.2);},.2);
                ui.step(1);return times;})()""")
            assert times == pytest.approx([0.2, 0.4])
            # A long real concept name must remain complete in both full-name surfaces.
            result = await browser.evaluate("""(()=>{const ui=NousOverlay;
                ui.dispatch({kind:'tick',shares:{'time-travel':.7,ocean:.2,Neutral:.1},beta:1,top_pushers:[],t:0});
                ui.dispatch({kind:'token',i:0,text:'',applied:null,color:null,
                    readout:{scores:{},top:null,margin:0},sky:{z:{'time-travel':20},drive:0}});
                return [...document.querySelectorAll('#share-legend span,.ridge-label')]
                    .map(e=>({text:e.textContent,fits:e.scrollWidth<=e.clientWidth}));})()""")
            assert any("TIME TRAVEL" in row["text"].upper() for row in result)
            assert all(row["fits"] for row in result)
            midpoint = await browser.evaluate(
                "NousOverlay.step(.3);document.querySelector('#share-bar span[data-faction=\"time-travel\"]').style.width"
            )
            assert float(midpoint.rstrip("%")) == pytest.approx(35)
            final = await browser.evaluate(
                "NousOverlay.step(.3);document.querySelector('#share-bar span[data-faction=\"time-travel\"]').style.width"
            )
            assert float(final.rstrip("%")) == pytest.approx(70)
            assert await browser.evaluate(
                "NousOverlay.dispatch({kind:'badge',label:'LIVE',quality:null,simulated_users:40});document.getElementById('source').textContent==='LIVE'&&!document.getElementById('sim-source').hidden&&document.getElementById('sim-source').textContent==='SIMULATED ×40'"
            )
            assert await browser.evaluate(
                "NousOverlay.dispatch({kind:'connection',service:'twitch',state:'reconnecting'});!document.getElementById('connection').hidden"
            )
            assert await browser.evaluate(
                "NousOverlay.dispatch({kind:'connection',service:'twitch',state:'connected'});document.getElementById('connection').hidden"
            )
            assert await browser.evaluate(
                "NousOverlay.step(20);NousOverlay.dispatch({kind:'mode',mode:'war',immune:false,prompt:'Make tea.',answer:999,phase:'generating',panel:'main'});NousOverlay.step(.7);document.getElementById('answer').classList.contains('thinking')"
            )
            assert await browser.evaluate(
                "(()=>{const ui=NousOverlay,frame=NOUS_TRACES.mock.war[0];ui.dispatch(frame);ui.step(1);const once=document.getElementById('answer').textContent;ui.dispatch(frame);ui.step(1);return document.getElementById('answer').textContent===once;})()"
            )
            assert not browser.errors

    asyncio.run(run())
