"""
src/api/security.py - Basic API protections.

Three pure-ASGI middlewares (pure so SSE streaming responses pass through
untouched) plus a cooldown dependency for expensive trigger endpoints:

  RateLimitMiddleware       per-client sliding-window request limit -> 429.
  BodySizeLimitMiddleware   reject oversized request bodies -> 413.
  SecurityHeadersMiddleware defensive response headers (nosniff, frame deny).
  trigger_cooldown(action)  429 when the action ran too recently.

Every limit is configured through Settings (COIMA_RATE_LIMIT_PER_MINUTE,
COIMA_MAX_BODY_BYTES, COIMA_TRIGGER_COOLDOWN_SECONDS); 0 disables it. State
is in-process: with multiple workers each process enforces its own window,
which is fine for a basic protection layer (the deploy nginx rate-limits at
the edge as well).
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Deque, Dict

from fastapi import Depends, HTTPException

from src.i18n.translator import t

from .config import get_settings
from .locale import get_locale

_WINDOW_SECONDS = 60.0
# When the per-client map grows past this, idle clients are pruned.
_CLIENT_MAP_SOFT_CAP = 4096


async def _send_json(send, status: int, payload: dict, extra_headers=()) -> None:
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *extra_headers,
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _client_key(scope) -> str:
    """Client identity for rate limiting: first X-Forwarded-For hop when a
    proxy set it (nginx does), else the socket peer address."""
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            first = value.decode("latin-1").split(",")[0].strip()
            if first:
                return first
            break
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """Sliding 60s window per client. OPTIONS (CORS preflight) and the
    liveness probe are exempt so limits never break browsers or orchestrators."""

    EXEMPT_PATHS = frozenset({"/api/health"})

    def __init__(self, app, limit_per_minute: int):
        self.app = app
        self.limit = limit_per_minute
        self._hits: Dict[str, Deque[float]] = {}

    def _prune_idle(self, now: float) -> None:
        if len(self._hits) <= _CLIENT_MAP_SOFT_CAP:
            return
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > _WINDOW_SECONDS]:
            del self._hits[key]

    async def __call__(self, scope, receive, send):
        if (
            self.limit <= 0
            or scope["type"] != "http"
            or scope["method"] == "OPTIONS"
            or scope["path"] in self.EXEMPT_PATHS
        ):
            return await self.app(scope, receive, send)

        now = time.monotonic()
        hits = self._hits.setdefault(_client_key(scope), deque())
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = max(1, int(_WINDOW_SECONDS - (now - hits[0])) + 1)
            return await _send_json(
                send, 429, {"detail": "Too many requests"},
                [(b"retry-after", str(retry).encode())],
            )
        hits.append(now)
        self._prune_idle(now)
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Reject requests whose Content-Length exceeds the cap. Bodies without a
    declared length are left to the server/edge proxy to bound (the deploy
    nginx enforces client_max_body_size regardless)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if self.max_bytes > 0 and scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == b"content-length":
                    try:
                        length = int(value)
                    except ValueError:
                        length = -1
                    if length < 0 or length > self.max_bytes:
                        return await _send_json(send, 413, {"detail": "Request body too large"})
                    break
        await self.app(scope, receive, send)


_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)


class SecurityHeadersMiddleware:
    """Append defensive headers unless already set by the app. The deploy
    nginx sets its own richer set (CSP, HSTS); these cover direct exposure."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                raw = message.setdefault("headers", [])
                existing = {name.lower() for name, _ in raw}
                for name, value in _SECURITY_HEADERS:
                    if name not in existing:
                        raw.append((name, value))
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Last accepted trigger per action name (monotonic seconds).
_last_trigger: Dict[str, float] = {}


def trigger_cooldown(action: str):
    """
    Dependency factory: 429 while `action` was triggered less than
    COIMA_TRIGGER_COOLDOWN_SECONDS ago. The timestamp is recorded when the
    check passes, so a run that later fails still starts the cooldown -
    exactly what protects the expensive endpoints from hammering. List it
    after any auth guard so rejected requests do not consume the cooldown.
    """

    def dependency(locale: str = Depends(get_locale)) -> None:
        cooldown = get_settings().trigger_cooldown_seconds
        if cooldown <= 0:
            return
        now = time.monotonic()
        last = _last_trigger.get(action)
        if last is not None and now - last < cooldown:
            retry = int(cooldown - (now - last)) + 1
            raise HTTPException(
                status_code=429,
                detail=t("errors.cooldown_active", locale, seconds=retry),
                headers={"Retry-After": str(retry)},
            )
        _last_trigger[action] = now

    return dependency
