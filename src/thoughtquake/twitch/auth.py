import asyncio
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import aiohttp

SCOPES = ("user:read:chat", "user:write:chat")
AUTH_BASE = "https://id.twitch.tv/oauth2"
HELIX_BASE = "https://api.twitch.tv/helix"


class AuthError(RuntimeError):
    pass


class TwitchHTTPError(RuntimeError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Twitch request failed (HTTP {status})")


@dataclass(frozen=True)
class Token:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float
    user_id: str = ""
    login: str = ""
    scopes: tuple[str, ...] = SCOPES


class TokenStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".config/thoughtquake/token.json"

    def load(self) -> Token:
        try:
            self.path.chmod(0o600)
            row = json.loads(self.path.read_text())
            row["scopes"] = tuple(row.get("scopes", SCOPES))
            return Token(**row)
        except (OSError, ValueError, TypeError) as exc:
            raise AuthError("Run thoughtquake auth to create a valid token store") from exc

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".token-", suffix=".tmp", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(asdict(token), handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class OAuth:
    def __init__(
        self,
        http: aiohttp.ClientSession,
        client_id: str,
        store: TokenStore,
        *,
        token: Token | None = None,
        auth_base: str = AUTH_BASE,
        helix_base: str = HELIX_BASE,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not client_id:
            raise AuthError("Set THOUGHTQUAKE_TWITCH_CLIENT_ID to your Public app's client ID")
        self.http, self.client_id, self.store = http, client_id, store
        self.token = token
        self.auth_base, self.helix_base = auth_base.rstrip("/"), helix_base.rstrip("/")
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        self.lock = asyncio.Lock()
        self.last_validated = float("-inf")

    async def _json(self, method: str, url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with self.http.request(method, url, allow_redirects=False, **kwargs) as response:
            try:
                body = await response.json()
            except (ValueError, aiohttp.ContentTypeError):
                body = {}
            return response.status, body

    async def authorize(self, show_code: Callable[[str, str], None]) -> Token:
        status, device = await self._json(
            "POST",
            self.auth_base + "/device",
            data={
                "client_id": self.client_id,
                "scopes": " ".join(SCOPES),
            },
        )
        if status != 200:
            raise AuthError("Could not start Device Code login; check your Public client ID")
        deadline = self.monotonic() + float(device["expires_in"])
        interval = max(1.0, float(device.get("interval", 5)))
        show_code(device["verification_uri"], device["user_code"])
        while self.monotonic() + interval < deadline:
            await self.sleep(interval)
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    status, result = await self._json(
                        "POST",
                        self.auth_base + "/token",
                        data={
                            "client_id": self.client_id,
                            "scopes": " ".join(SCOPES),
                            "device_code": device["device_code"],
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
            except TimeoutError:
                break
            if status == 200:
                self.token = Token(
                    result["access_token"],
                    result["refresh_token"],
                    self.clock() + float(result["expires_in"]),
                )
                # Save a one-use refresh token before validation or other network work.
                self.store.save(self.token)
                return await self.validate()
            error = result.get("message", result.get("error", ""))
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise AuthError("Device Code login was denied or expired; run thoughtquake auth again")
        raise AuthError("Device Code expired; run thoughtquake auth again")

    def _loaded(self) -> Token:
        if self.token is None:
            self.token = self.store.load()
        return self.token

    async def _refresh(self) -> Token:
        old = self._loaded()
        status, result = await self._json(
            "POST",
            self.auth_base + "/token",
            data={
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": old.refresh_token,
            },
        )
        if status != 200:
            raise AuthError("Twitch login expired or was revoked; run thoughtquake auth again")
        self.token = replace(
            old,
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            expires_at=self.clock() + float(result["expires_in"]),
        )
        self.store.save(self.token)
        return self.token

    async def access(self, failed: str | None = None) -> Token:
        async with self.lock:
            token = self._loaded()
            if (failed is not None and token.access_token == failed) or (
                failed is None and token.expires_at - self.clock() <= 300
            ):
                token = await self._refresh()
            return token

    async def validate(self) -> Token:
        token = await self.access()
        async with self.lock:
            # Another caller may have refreshed while this caller waited for the lock.
            token = self._loaded()
            for attempt in range(2):
                status, body = await self._json(
                    "GET",
                    self.auth_base + "/validate",
                    headers={
                        "Authorization": "OAuth " + token.access_token,
                    },
                )
                if status == 401 and not attempt:
                    token = await self._refresh()
                    continue
                if status != 200:
                    raise AuthError("Twitch token validation failed; run thoughtquake auth again")
                if body.get("client_id") != self.client_id or not set(SCOPES) <= set(
                    body.get("scopes", [])
                ):
                    raise AuthError("Twitch token belongs to another app or lacks chat scopes")
                if not body.get("user_id") or not body.get("login"):
                    raise AuthError("Twitch requires a user token")
                if token.user_id and body["user_id"] != token.user_id:
                    raise AuthError("Twitch token identity changed; run thoughtquake auth again")
                token = replace(
                    token,
                    user_id=body["user_id"],
                    login=body["login"],
                    expires_at=self.clock() + float(body["expires_in"]),
                    scopes=tuple(body["scopes"]),
                )
                self.token = token
                self.store.save(token)
                self.last_validated = self.monotonic()
                return token
        raise AuthError("Twitch validation failed")

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = await self.access()
        for attempt in range(2):
            status, body = await self._json(
                method,
                self.helix_base + path,
                headers={
                    "Client-Id": self.client_id,
                    "Authorization": "Bearer " + token.access_token,
                },
                **kwargs,
            )
            if status == 401 and not attempt:
                token = await self.access(failed=token.access_token)
                continue
            if status == 401:
                raise AuthError("Twitch rejected the refreshed token; run thoughtquake auth again")
            if not 200 <= status < 300:
                raise TwitchHTTPError(status)
            return body
        raise AuthError("Twitch authentication failed")

    async def maintain(self) -> None:
        while True:
            await self.sleep(60)
            await self.access()
            if self.monotonic() - self.last_validated >= 3600:
                await self.validate()
