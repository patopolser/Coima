"""
src/mcp_server/http.py - The /mcp Streamable HTTP endpoint for the FastAPI app.

Stateless JSON-response mode: each POST is self-contained, which suits a
read-mostly tool server behind uvicorn and needs no sticky sessions.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .server import mcp

_LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


class MCPHttpEndpoint:
    """
    ASGI endpoint: optional bearer-token check, then the SDK's Streamable
    HTTP app. The SDK session manager can run only once per instance, so every
    host lifespan (e.g. each TestClient) builds a fresh one via lifespan().
    """

    def __init__(self, token: Optional[str] = None, extra_hosts: str = ""):
        self._token = token or None
        extra = [h.strip() for h in extra_hosts.split(",") if h.strip()]
        # Host/Origin validation guards against DNS rebinding from a browser.
        self._security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_LOCAL_HOSTS + extra,
            allowed_origins=_LOCAL_ORIGINS + [f"http://{h}" for h in extra] + [f"https://{h}" for h in extra],
        )
        self._app: Optional[ASGIApp] = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        app = mcp.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            transport_security=self._security,
        )
        async with mcp.session_manager.run():
            self._app = app
            try:
                yield
            finally:
                self._app = None

    def _authorized(self, scope: Scope) -> bool:
        if self._token is None:
            return True
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        scheme, _, given = auth.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(given.strip(), self._token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            await JSONResponse({"detail": "MCP server is not running"}, status_code=503)(scope, receive, send)
            return
        if not self._authorized(scope):
            await JSONResponse(
                {"detail": "Missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        await self._app(scope, receive, send)
