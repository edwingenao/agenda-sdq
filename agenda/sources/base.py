"""Clase base de los adaptadores. Un adaptador = una fuente; si un sitio cambia, solo se arregla ese archivo."""

from __future__ import annotations

from datetime import date

from agenda import llm
from agenda.db import DB
from agenda.dates import month_day  # noqa: F401  (reexport cómodo para adaptadores)
from agenda.htmlutil import fingerprint
from agenda.http import Fetcher
from agenda.models import Event, guess_kids, normalize_category, zone_for


class Source:
    id: str = ""
    name: str = ""
    delay: float = 3.0  # segundos mínimos entre peticiones al sitio
    default_zone: str = ""
    default_max_details: int | None = None

    def __init__(
        self,
        fetcher: Fetcher,
        db: DB,
        today: date,
        now: str,
        max_details: int | None = None,
        log=print,
    ):
        self.fetcher = fetcher
        self.db = db
        self.today = today
        self.now = now
        self.max_details = max_details if max_details is not None else self.default_max_details
        self.log = log

    def fetch_page(self, url: str, force: bool = False) -> tuple[str, str, bool]:
        """(html, huella, cambió). Si no cambió, se marca como visto y el adaptador la salta."""
        html = self.fetcher.get(url, delay=self.delay).text
        fp = fingerprint(html)
        changed = force or self.db.page_changed(url, fp)
        if not changed:
            self.db.touch_url(url, self.now)
        return html, fp, changed

    def llm_event(self, url: str, lines: list[str]) -> Event | None:
        """Último recurso cuando los selectores fallan. Marca el evento para revisión humana."""
        data = llm.extract(lines, url, self.today)
        if not data:
            return None
        try:
            dates = sorted({date.fromisoformat(d).isoformat() for d in data["dates"]})
        except (ValueError, TypeError):
            return None
        venue = data.get("venue") or ""
        return Event(
            source=self.id,
            source_name=self.name,
            url=url,
            title=data["title"],
            dates=dates,
            start_time=data.get("start_time"),
            venue=venue,
            zone=zone_for(venue, self.default_zone),
            category=data.get("category") or normalize_category(data["title"]),
            is_free=data.get("is_free"),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            kids=guess_kids(data["title"]),
            needs_review=True,
        )

    def run(self) -> list[Event]:  # pragma: no cover - lo implementa cada fuente
        raise NotImplementedError
