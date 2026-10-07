"""Cliente HTTP cortés: respeta robots.txt (con comodines), espera entre peticiones y reintenta."""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx
from protego import Protego

from agenda import __version__

AGENT = "AgendaCulturalSDQ"


class Disallowed(Exception):
    """robots.txt no permite la URL (o no se pudo leer robots.txt)."""


class Fetcher:
    def __init__(
        self,
        default_delay: float = 3.0,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        contact = os.environ.get("AGENDA_CONTACT", "define AGENDA_CONTACT con tu correo")
        ua = f"{AGENT}/{__version__} (proyecto personal; contacto: {contact})"
        self.default_delay = default_delay
        self._sleep = sleep
        self._clock = clock
        self._client = httpx.Client(
            headers={"User-Agent": ua, "Accept-Language": "es-DO,es;q=0.9,en;q=0.5"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._robots: dict[str, Protego] = {}
        self._last: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def _robots_for(self, url: str) -> Protego:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        try:
            r = self._client.get(origin + "/robots.txt")
        except httpx.HTTPError as e:
            raise Disallowed(f"no se pudo leer robots.txt de {origin}: {e}") from e
        if r.status_code == 200:
            rp = Protego.parse(r.text)
        elif 400 <= r.status_code < 500:
            rp = Protego.parse("")  # sin robots.txt: todo permitido
        else:
            raise Disallowed(f"robots.txt de {origin} respondió {r.status_code}; se omite por precaución")
        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(url, AGENT)

    def get(self, url: str, delay: float | None = None, params: dict | None = None) -> httpx.Response:
        rp = self._robots_for(url)
        if not rp.can_fetch(url, AGENT):
            raise Disallowed(f"robots.txt no permite {url}")
        host = urlparse(url).netloc
        wait = max(self.default_delay if delay is None else delay, rp.crawl_delay(AGENT) or 0)
        last = self._last.get(host)
        if last is not None:
            elapsed = self._clock() - last
            if elapsed < wait:
                self._sleep(wait - elapsed)
        err: Exception | None = None
        for attempt in range(3):
            try:
                r = self._client.get(url, params=params)
                self._last[host] = self._clock()
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError("5xx", request=r.request, response=r)
                r.raise_for_status()
                return r
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
                err = e
                self._last[host] = self._clock()
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    break
                self._sleep(2 * (attempt + 1))
        assert err is not None
        raise err
