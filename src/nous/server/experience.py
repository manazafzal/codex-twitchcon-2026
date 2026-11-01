"""A local welcome screen switches sources only after the previous owner has stopped."""

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from importlib.resources import files
from typing import Any

import aiohttp
from aiohttp import web

from nous.config import data_dir, library_path, model_dir, save_settings, settings
from nous.engine.events import Badge, Connection, Event, Mode, event_from_dict
from nous.server.app import APP_KEY, create_app
from nous.server.leaderboard import Leaderboard
from nous.server.state import ViewState
from nous.twitch.auth import AUTH_BASE, HELIX_BASE, AuthError, OAuth, TokenStore

log = logging.getLogger(__name__)


class RecordedDemo:
    def __init__(self, *, sleep: Callable = asyncio.sleep) -> None:
        self.sleep = sleep
        self.data = json.loads(files("nous.sim").joinpath("demo_round.json").read_text())

    async def events(self) -> AsyncIterator[Event]:
        number = 0
        while True:
            from nous.concepts.library import load_concepts

            initial = ViewState(load_concepts()).snapshot()
            initial.state["badge"] = Badge(
                "SIMULATED ×40", "RECORDING · Pretend chat · Test AI", 40
            ).to_dict()
            yield initial
            recordings = self.data.get("rounds", [self.data])
            recording = recordings[number % len(recordings)]
            previous = 0.0
            for item in recording["rows"]:
                await self.sleep(max(0, item["at"] - previous))
                previous = item["at"]
                event = event_from_dict(item["event"])
                if isinstance(event, Mode):
                    event = replace(event, answer=event.answer + number * 10, round_id=number + 1)
                    if event.phase == "generating":
                        event = replace(event, remaining=6.4)
                yield event
            await self.sleep(max(0, recording["duration"] - previous))
            number += 1


class Experience:
    def __init__(self, *, auth_base: str = AUTH_BASE, helix_base: str = HELIX_BASE) -> None:
        self.kind = "welcome"
        self.factory: Callable[[], AsyncIterator[Event]] | None = None
        self.changed = asyncio.Event()
        self.version = 0
        self.session: Any = None
        self.auth_base, self.helix_base = auth_base, helix_base
        self.login_task: asyncio.Task | None = None
        self.signed_in = False
        self.login: dict[str, Any] = {
            "status": "idle",
            "message": "Ready! Try the demo. No Twitch needed.",
        }
        self.client_id = os.getenv("NOUS_TWITCH_CLIENT_ID") or settings().get("client_id", "")
        self.server: Any = None
        self.current_board = Leaderboard()
        self.board = Leaderboard(
            data_dir() / "leaderboard.json", stream_id=os.getenv("NOUS_STREAM_ID")
        )

    def use(self, factory: Callable[[], AsyncIterator[Event]]) -> None:
        self.factory = factory
        self.version += 1
        self.changed.set()

    def game_board(self, board: Leaderboard) -> None:
        self.current_board = board
        if self.server:
            self.server.leaderboard = board

    def demo(self) -> None:
        self.kind = "demo"
        self.session = None
        self.game_board(Leaderboard())
        self.use(self.demo_events)

    async def demo_events(self) -> AsyncIterator[Event]:
        if library_path().exists() and (model_dir() / "config.json").exists():
            try:
                from nous.concepts.library import ConceptLibrary
                from nous.model.hf_backend import HFBackend
                from nous.server.session import Session
                from nous.sim.crowd import Crowd

                backend = await asyncio.to_thread(HFBackend, local_path=str(model_dir()))
                library = await asyncio.to_thread(ConceptLibrary.load, library_path())
                self.session = Session(
                    backend=backend, library=library, crowd=Crowd(), leaderboard=self.current_board
                )
            except (ImportError, OSError, ValueError):
                self.session = None
        stream = self.session.events() if self.session else RecordedDemo().events()
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    def start_round(self) -> None:
        if self.session:
            self.session.start_round()
        else:
            self.demo()

    def switch_mode(self, mode: str) -> None:
        if self.session:
            self.session.switch_mode(mode)

    def set_immune(self, enabled: bool) -> None:
        if self.session:
            self.session.set_immune(enabled)

    async def events(self) -> AsyncIterator[Event]:
        if self.factory is None:
            yield Badge("SIMULATED ×0", "Choose Try the demo to start", 0)
        while True:
            self.changed.clear()
            if self.factory is None:
                await self.changed.wait()
                continue
            if self.server:
                from nous.concepts.library import load_concepts
                from nous.server.presentation import Presentation

                self.server.presentation = Presentation(load_concepts())
                self.server.last_tick = None
                initial = ViewState(load_concepts()).snapshot()
                if self.kind == "live":
                    initial.state["badge"] = Badge("LIVE").to_dict()
                    initial.state["connections"] = {"twitch": "reconnecting"}
                elif self.kind == "demo":
                    initial.state["badge"] = Badge(
                        "SIMULATED ×40", "Getting your demo ready", 40
                    ).to_dict()
                yield initial
            queue: asyncio.Queue = asyncio.Queue(maxsize=64)
            factory, version = self.factory, self.version

            async def pump(factory: Callable = factory, queue: asyncio.Queue = queue) -> None:
                stream = factory()
                try:
                    async for event in stream:
                        if isinstance(event, Connection) and event.service == "twitch":
                            if event.state == "connected":
                                self.login = {
                                    "status": "live",
                                    "message": "Connected! Open your game and type !join in Twitch chat.",
                                }
                            elif event.state in {"auth_required", "revoked"}:
                                self.signed_in = False
                                self.login = {
                                    "status": "error",
                                    "message": "Twitch needs permission again. Click Try login again.",
                                    "stage": "login",
                                }
                        await queue.put(event)
                    await queue.put(RuntimeError("The game stopped. Please retry."))
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - keep private failures out of browser messages
                    await queue.put(RuntimeError("The game paused. Please try again."))
                finally:
                    await stream.aclose()

            owner = asyncio.create_task(pump())
            switch = asyncio.create_task(self.changed.wait())
            read = None
            try:
                while version == self.version:
                    read = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        (read, switch), return_when=asyncio.FIRST_COMPLETED
                    )
                    if switch in done:
                        break
                    event = read.result()
                    if isinstance(event, Exception):
                        raise event
                    yield event
            finally:
                for task in (read, switch, owner):
                    if task:
                        task.cancel()
                await asyncio.gather(
                    *(t for t in (read, switch, owner) if t), return_exceptions=True
                )

    async def authorize(self) -> None:
        self.signed_in = False
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20), trust_env=self.auth_base == AUTH_BASE
            ) as http:
                auth = OAuth(
                    http,
                    self.client_id,
                    TokenStore(data_dir() / "token.json"),
                    auth_base=self.auth_base,
                    helix_base=self.helix_base,
                )

                def show(uri: str, code: str) -> None:
                    self.login = {
                        "status": "waiting",
                        "message": "Open Twitch, enter this code, and choose Authorize.",
                        "url": uri,
                        "code": code,
                    }

                token = await auth.authorize(show)
                self.signed_in = True
                self.login = {
                    "status": "connected",
                    "message": "You're signed in!",
                    "name": token.login,
                }
                save_settings({**settings(), "client_id": self.client_id})
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep private failures out of browser messages
            self.login = {
                "status": "error",
                "message": "Twitch could not finish signing in. Check your internet, check your app code, then click Try login again.",
                "stage": "login",
            }

    async def connect(self, channel: str) -> None:
        from nous.concepts.builder import build_library
        from nous.concepts.library import ConceptLibrary, load_concepts
        from nous.model.hf_backend import HFBackend
        from nous.server.session import Session
        from nous.sim.crowd import Crowd
        from nous.twitch.live import LiveSession

        if not (model_dir() / "config.json").exists():
            raise ValueError(
                "The AI download isn't ready. Try the recorded demo now, or run setup.bat again, then click Retry."
            )
        self.login["message"] = "Getting the AI ready. You can watch the recording while you wait."
        backend = await asyncio.to_thread(HFBackend, local_path=str(model_dir()))
        if library_path().exists():
            library = await asyncio.to_thread(ConceptLibrary.load, library_path())
        else:
            library = await asyncio.to_thread(
                build_library,
                backend,
                load_concepts(),
                samples=2,
                neutral_samples=60,
                median_norm=26.78,
                model_id="Qwen/Qwen2.5-0.5B-Instruct",
            )
            library.save(library_path())
        session = Session(
            backend=backend,
            library=library,
            crowd=Crowd(twitch_connected=True),
            source="LIVE",
            leaderboard=self.board,
        )
        live = LiveSession(
            session,
            self.client_id,
            channel,
            store=TokenStore(data_dir() / "token.json"),
            auth_base=self.auth_base,
            helix_base=self.helix_base,
        )
        # Validate the channel before promising that the game can start.
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
            auth = OAuth(
                http,
                self.client_id,
                TokenStore(data_dir() / "token.json"),
                auth_base=self.auth_base,
                helix_base=self.helix_base,
            )
            await auth.validate()
            users = await auth.request("GET", "/users", params={"login": channel})
            if not users.get("data"):
                raise ValueError(
                    "We couldn't find that channel. Use its Twitch name and click Retry."
                )
        self.session = session
        self.kind = "live"
        self.game_board(self.board)
        self.use(live.events)
        self.login = {
            "status": "connecting",
            "message": "Listening for your Twitch chat...",
        }


def add_welcome(app: web.Application, experience: Experience, *, home: bool = False) -> None:
    server = app[APP_KEY]

    async def protected(request: web.Request) -> dict:
        server.authorize(request)
        try:
            return await request.json()
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Please try that step again.") from exc

    async def status(request: web.Request) -> web.Response:
        server.authorize(request)
        return web.json_response(
            {
                **experience.login,
                "has_app_code": bool(experience.client_id),
                "signed_in": experience.signed_in,
                "brain_downloaded": (model_dir() / "config.json").exists(),
            }
        )

    async def demo(request: web.Request) -> web.Response:
        await protected(request)
        experience.demo()
        return web.json_response(
            {
                "url": "/overlay/",
                "recording": not (
                    library_path().exists() and (model_dir() / "config.json").exists()
                ),
            }
        )

    async def login(request: web.Request) -> web.Response:
        body = await protected(request)
        value = str(body.get("app_code") or experience.client_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", value):
            raise web.HTTPBadRequest(text="Copy the app code from Twitch, then try again.")
        if experience.login_task and not experience.login_task.done():
            raise web.HTTPConflict(
                text="Login is already open. Finish it in Twitch or wait for the retry button."
            )
        experience.client_id = value
        experience.login = {"status": "starting", "message": "Opening your Twitch sign-in..."}
        experience.login_task = asyncio.create_task(experience.authorize())
        return web.json_response(experience.login)

    async def connect(request: web.Request) -> web.Response:
        body = await protected(request)
        channel = str(body.get("channel") or experience.login.get("name", "")).strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,25}", channel):
            raise web.HTTPBadRequest(text="Type your Twitch channel name, then retry.")
        if not experience.signed_in:
            raise web.HTTPBadRequest(text="Finish signing in to Twitch first.")
        if experience.login_task and not experience.login_task.done():
            raise web.HTTPConflict(text="That step is still running. Please wait.")

        async def prepare() -> None:
            try:
                await experience.connect(channel)
            except AuthError:
                experience.signed_in = False
                experience.login = {
                    "status": "error",
                    "stage": "login",
                    "message": "Twitch needs permission again. Click Try login again.",
                }
            except Exception:  # noqa: BLE001 - keep private failures out of browser messages
                experience.login = {
                    "status": "error",
                    "message": "We couldn't open the game. Check your channel name and internet. If the AI download is unfinished, run setup.bat again. Then click Retry.",
                    "stage": "connect",
                }

        experience.login = {
            "status": "preparing",
            "message": "Getting your game ready. First-time preparation can take several minutes. You can try the recording in another tab.",
        }
        experience.login_task = asyncio.create_task(prepare())
        return web.json_response(experience.login)

    async def bootstrap(request: web.Request) -> web.Response:
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            raise web.HTTPForbidden(text="Open NOUS from setup.bat to unlock this page.")
        server.authorize(request)
        response = web.json_response({"ready": True})
        response.set_cookie(
            "nous_control", server.control_token, httponly=True, samesite="Strict", path="/"
        )
        return response

    app.router.add_post("/api/bootstrap", bootstrap)
    app.router.add_get("/api/welcome", status)
    app.router.add_post("/api/demo", demo)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/connect", connect)

    async def cleanup(application: web.Application) -> None:
        if experience.login_task:
            experience.login_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await experience.login_task

    app.on_cleanup.append(cleanup)


def make_experience_app(
    *, token: str | None = None, demo: bool = False, experience: Experience | None = None
) -> web.Application:
    experience = experience or Experience()
    if demo:
        experience.demo()
    from nous.concepts.library import load_concepts

    app = create_app(
        concepts=load_concepts(),
        source=experience.events,
        control_token=token,
        switch_mode=experience.switch_mode,
        set_immune=experience.set_immune,
        leaderboard=experience.current_board,
        start_round=experience.start_round,
        welcome_home=not demo,
    )
    experience.server = app[APP_KEY]
    add_welcome(app, experience)
    return app


def serve(args: Any, *, welcome: bool) -> None:
    import webbrowser

    token = secrets.token_urlsafe(32)
    app = make_experience_app(token=token, demo=not welcome)
    root = f"http://{args.host}:{args.port}"
    url = root + ("/welcome.html#" + token if welcome else "/overlay/")

    async def startup(application: web.Application) -> None:
        log.info("NOUS: %s", url)
        log.info("Your private controls: %s/control#%s", root, token)
        if not args.no_browser:
            webbrowser.open(url)

    app.on_startup.append(startup)
    web.run_app(app, host=args.host, port=args.port, print=None)
