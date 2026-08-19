"""
session.py - HTTP session management for the ASP.NET WebForms portal.

Wraps `requests.Session` with persistent cookies, optional retry/back-off,
optional inter-request delay, optional User-Agent rotation (all disabled by
default), and a VIEWSTATE extraction helper.

Usage:

    with ScraperSession() as session:
        html = session.get("https://comprar.gob.ar/BuscarAvanzado.aspx")
        viewstate = session.extract_viewstate(html)
"""

from __future__ import annotations

import random
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Used only when settings.rotate_user_agent is True.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def decode_response(response: requests.Response) -> str:
    """Decode a portal response tolerating mixed/incorrect encodings.

    contratar.gob.ar declares UTF-8 but serves a mix of valid UTF-8, raw
    Latin-1 bytes (e.g. 0xD3 for 'Ó' in DB-sourced text), and double-encoded
    UTF-8 ("Ã³" for 'ó'). Plain ``response.text`` turns the Latin-1 bytes
    into U+FFFD. This decoder:

      1. Decodes UTF-8 with ``surrogateescape`` so undecodable bytes survive.
      2. Maps each escaped byte back through cp1252 (covers the raw Latin-1).
      3. Repairs double-encoded runs when doing so strictly round-trips and
         reduces mojibake markers.
    """
    raw = response.content
    text = raw.decode("utf-8", errors="surrogateescape")

    if any("\udc80" <= ch <= "\udcff" for ch in text):
        text = "".join(
            bytes([ord(ch) - 0xDC00]).decode("cp1252", errors="replace")
            if "\udc80" <= ch <= "\udcff" else ch
            for ch in text
        )

    if "Ã" in text or "Â" in text:
        try:
            repaired = text.encode("cp1252").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            repaired = None
        if repaired is not None and (
            repaired.count("Ã") + repaired.count("Â") < text.count("Ã") + text.count("Â")
        ):
            text = repaired
    return text


class ScraperSession:
    """Context-manager-compatible wrapper around requests.Session.

    Preserves cookies, handles ASP.NET VIEWSTATE, and applies optional
    anti-rate-limit measures (all disabled by default).
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._configure_retry()
        self._set_default_headers()
        self._last_request_time: float = 0.0
        self._warmed_up: bool = False

    def warm_up(self) -> None:
        """Establish portal session cookies by visiting the home page once.

        contratar.gob.ar bounces cold requests to BuscarAvanzado.aspx back to
        Default.aspx until an ASP.NET session cookie exists; comprar.gob.ar
        tolerates the extra request, so the warm-up runs for both portals.
        """
        if self._warmed_up:
            return
        try:
            self.get(f"{settings.base_url}/Default.aspx")
        except Exception as exc:
            logger.warning("Session warm-up failed (continuing anyway): %s", exc)
        self._warmed_up = True

    def __enter__(self) -> "ScraperSession":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def _configure_retry(self) -> None:
        """Attach an HTTPAdapter with retry logic (disabled when max_retries=0)."""
        retry = Retry(
            total=settings.max_retries,
            backoff_factor=settings.retry_backoff_factor,
            status_forcelist=(
                settings.retry_status_forcelist
                if settings.max_retries > 0
                else []
            ),
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _set_default_headers(self) -> None:
        """Apply common browser-like headers to the session."""
        ua = (
            random.choice(_USER_AGENTS)
            if settings.rotate_user_agent
            else settings.user_agent
        )
        self._session.headers.update(
            {
                "User-Agent": ua,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )

    def _apply_delay(self) -> None:
        """Enforce the inter-request delay if configured (default: 0 = no delay)."""
        if settings.request_delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_time
        wait = settings.request_delay_seconds - elapsed
        if wait > 0:
            logger.debug("Rate-limit delay: sleeping %.2fs", wait)
            time.sleep(wait)

    def _rotate_ua_if_needed(self) -> None:
        """Rotate User-Agent before each request if the setting is enabled."""
        if settings.rotate_user_agent:
            self._session.headers["User-Agent"] = random.choice(_USER_AGENTS)

    def get(self, url: str, **kwargs) -> str:
        """GET a URL and return the response text.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        self._apply_delay()
        self._rotate_ua_if_needed()
        kwargs.setdefault("timeout", settings.request_timeout)
        logger.debug("GET %s", url)
        response = self._session.get(url, **kwargs)
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return decode_response(response)

    def post(self, url: str, data: dict, **kwargs) -> str:
        """POST form data to a URL and return the response text.

        The `data` dict must include the ASP.NET VIEWSTATE fields when posting
        to a WebForms page.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        self._apply_delay()
        self._rotate_ua_if_needed()
        kwargs.setdefault("timeout", settings.request_timeout)
        logger.debug("POST %s  [%d form keys]", url, len(data))
        response = self._session.post(url, data=data, **kwargs)
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        return decode_response(response)

    @staticmethod
    def extract_viewstate(html: str) -> dict[str, str]:
        """Parse the ASP.NET hidden fields required for any postback.

        Returns a dict with keys __VIEWSTATE, __VIEWSTATEGENERATOR,
        __EVENTVALIDATION. Values are empty strings if the field is absent
        (safe to include in POST).
        """
        soup = BeautifulSoup(html, "lxml")
        fields = [
            "__VIEWSTATE",
            "__VIEWSTATEGENERATOR",
            "__EVENTVALIDATION",
        ]
        result: dict[str, str] = {}
        for field in fields:
            tag = soup.find("input", {"id": field})
            result[field] = tag["value"] if tag else ""
        return result
