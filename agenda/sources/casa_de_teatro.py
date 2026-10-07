"""Casa de Teatro (casadeteatro.org/agenda): JSON de su propia API.

Verificado el 5 oct 2026 con el navegador (pestaña Red): la página es una app React (HTML vacío) que pide
    GET /api/events?limit=50&upcoming=true      -> eventos próximos
    GET /api/events?limit=50&upcoming=false     -> pasados
robots.txt: `Allow: /`; su sitemap apunta a casadeteatro.com.do (mismo organismo, otro dominio).
Campos: titulo, slug, descripcion_corta, fecha_inicio (UTC ISO), fecha_fin, tipo (musica|teatro|cine|literatura|
taller|expo), precio / precio_max (texto "1000.00"), ticket_url (tix.do, ticketmax), espacio.nombre.
Ese día `upcoming=true` devolvía [] (lo más reciente era del 30 jul): la fuente puede ir vacía por semanas.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from agenda.models import Event, guess_kids, normalize_category
from agenda.sources.base import Source

BASE = "https://casadeteatro.org"
API = BASE + "/api/events?limit=50&upcoming=true"
TZ_SDQ = timezone(timedelta(hours=-4))  # República Dominicana: UTC-4 todo el año
TIPOS = {
    "musica": "Música",
    "teatro": "Teatro",
    "cine": "Cine",
    "expo": "Arte",
    "literatura": "Cultura",
    "taller": "Cultura",
}
JAZZ = re.compile(r"\bjazz|bossa|swing|bebop|blues\b", re.I)


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ_SDQ)
    except ValueError:
        return None


def _money(v) -> int | None:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def parse_events(payload: str | list, today) -> list[Event]:
    items = json.loads(payload) if isinstance(payload, str) else payload
    if isinstance(items, dict):  # por si algún día lo envuelven: {"data": [...]}
        items = items.get("data") or items.get("events") or []
    merged: dict[tuple[str, str], Event] = {}
    for it in items:
        if it.get("estado") not in (None, "publicado"):
            continue
        start = _local(it.get("fecha_inicio"))
        title = (it.get("titulo") or "").strip()
        if not start or not title:
            continue
        end = _local(it.get("fecha_fin")) or start
        dates = [start.date().isoformat()]
        if end.date() > start.date():
            dates = [(start.date() + timedelta(days=i)).isoformat() for i in range((end.date() - start.date()).days + 1)]
        if dates[-1] < today.isoformat():
            continue
        venue = (it.get("espacio") or {}).get("nombre") or ""
        venue = f"{venue}, Casa de Teatro" if venue else "Casa de Teatro"

        pmin, pmax = _money(it.get("precio")), _money(it.get("precio_max"))
        review = False
        if pmin is None:
            is_free = None
        elif pmin == 0 and not pmax:
            is_free = True
        else:
            is_free = False
        if pmax is not None and pmin is not None and pmax <= pmin:
            pmax = None

        desc = (it.get("descripcion_corta") or "").strip()
        tags = ["jazz"] if JAZZ.search(f"{title} {desc}") else []
        tipo = (it.get("tipo") or "").lower()
        if tipo == "taller":
            tags.append("formacion")
        category = TIPOS.get(tipo) or normalize_category(title, desc)

        # Cada función es un registro aparte; las agrupamos por título y sala.
        k = (title.casefold(), venue)
        if k in merged:
            ev = merged[k]
            ev.dates = sorted(set(ev.dates + dates))
            continue
        merged[k] = Event(
            source="casa_de_teatro",
            source_name="Casa de Teatro",
            url=f"{BASE}/agenda#{it.get('slug') or title}",
            title=title,
            dates=dates,
            start_time=None if (start.hour, start.minute) == (0, 0) else start.strftime("%H:%M"),
            venue=venue,
            zone="Ciudad Colonial",
            category=category,
            is_free=is_free,
            price_min=pmin if is_free is False else (0 if is_free else None),
            price_max=pmax,
            kids=guess_kids(title, desc),
            tags=tags,
            description=desc[:280],
            ticket_url=it.get("ticket_url") or "",
            needs_review=review,
        )
    return list(merged.values())


class CasaDeTeatro(Source):
    id = "casa_de_teatro"
    name = "Casa de Teatro"
    delay = 3.0
    default_zone = "Ciudad Colonial"

    def run(self) -> list[Event]:
        text = self.fetcher.get(API, delay=self.delay).text
        events = parse_events(text, self.today)
        if not events:
            self.log(f"[{self.id}] 0 eventos próximos (la API respondió pero está vacía; puede ser normal).")
        return events
