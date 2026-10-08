"""Ticketmax (ticketmax.org; ticketmax.com.do redirige ahí): ticketera dominicana con datos estructurados.

Verificado el 7 oct 2026 desde la PC:
  - robots.txt solo bloquea /wp-admin/ (y pide 10 s a los bots de Meta). WordPress + WooCommerce.
  - La portada lista los eventos vigentes como tarjetas `.tm-event-card` con `data-city`, `data-venue`, `data-cats` y
    un enlace a /evento/<id>/ (68 tarjetas ese día, 56 en Santo Domingo). El sitemap de productos tiene 174, con
    eventos viejos: por eso se parte de la portada y no del sitemap.
  - Cada /evento/<id>/ trae JSON-LD `Event`: `name` ("FDT 10x10 | LA LEYENDA DE ROBIN HOOD | | 8:30 PM | Viernes 6
    Noviembre 2026"), `startDate` con zona ("2026-11-06T20:30:00-04:00"), `offers` en DOP (`lowPrice`/`highPrice`),
    `location` con `addressLocality` y `description`.

Reglas: solo Santo Domingo (la tarjeta y, si el JSON-LD la trae, la ciudad de `location`); fuera congresos, tours,
deportes y televisión; la hora sale de `startDate` en hora de Santo Domingo; el precio, de `offers`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from agenda.dates import TZ_SDQ
from agenda.htmlutil import parse
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

HOME = "https://ticketmax.org/"
MAX_DESCRIPTION = 280
SDQ = {"santo domingo", "distrito nacional", "santo domingo este", "santo domingo oeste", "santo domingo norte"}
SKIP_CATS = {"congresos", "tours", "deportes", "television"}
CATS = {
    "conciertos": "Música", "musica": "Música", "party": "Música", "dj-party": "Música", "festival": "Música",
    "teatro": "Teatro", "comedia": "Teatro", "arte": "Arte", "cata": "Gastronomía",
}
_TIME_PART = re.compile(r"^\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?$", re.I)
_DATE_PART = re.compile(r"^(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)?\s*\d{1,2}\s+\w+\s+\d{4}$", re.I)


def parse_cards(html: str) -> list[dict]:
    """Tarjetas de la portada: [{url, city, venue, cats, title}], sin repetir URL."""
    out, seen = [], set()
    for card in parse(html).css(".tm-event-card"):
        link = card.css_first('a[href*="/evento/"]')
        if not link:
            continue
        url = re.sub(r"(/evento/\d+/).*$", r"\1", link.attributes.get("href") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        a = card.attributes
        out.append({
            "url": url,
            "city": (a.get("data-city") or "").strip(),
            "venue": (a.get("data-venue") or "").strip(),
            "cats": (a.get("data-cats") or "").split(),
            "title": (a.get("data-title") or "").strip(),
        })
    return out


def event_ld(html: str) -> dict | None:
    """El objeto JSON-LD de tipo Event de la página, o None."""
    for raw in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and it.get("@type") == "Event":
                return it
    return None


def clean_title(name: str) -> str:
    """Quita la hora y la fecha que Ticketmax pega al nombre: "A | B | | 8:30 PM | Viernes 6 Noviembre 2026" -> "A | B"."""
    parts = [p.strip() for p in (name or "").split("|")]
    keep = [p for p in parts if p and not _TIME_PART.match(p) and not _DATE_PART.match(p)]
    return " | ".join(keep) or (name or "").strip()


def _description(text: str) -> str:
    text = text or ""
    if "SINOPSIS:" in text.upper():
        text = text[text.upper().index("SINOPSIS:") + len("SINOPSIS:"):]
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_DESCRIPTION else text[: MAX_DESCRIPTION - 1].rstrip() + "…"


def _price(offers) -> tuple[bool | None, int | None, int | None]:
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict) or offers.get("priceCurrency", "DOP") != "DOP":
        return None, None, None

    def num(v):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None

    lo = num(offers.get("lowPrice", offers.get("price")))
    hi = num(offers.get("highPrice"))
    if lo is None:
        return None, None, None
    if lo == 0 and not hi:
        return True, 0, None
    return False, lo, hi if hi and hi > lo else None


def parse_event(card: dict, html: str, today) -> Event | None:
    """Un evento a partir de su tarjeta y su página; None si no es de Santo Domingo, ya pasó o no trae fecha."""
    ld = event_ld(html)
    if not ld:
        return None
    try:
        start = datetime.fromisoformat(str(ld.get("startDate"))).astimezone(TZ_SDQ)
    except (TypeError, ValueError):
        return None
    if start.date() < today:
        return None
    loc = ld.get("location") if isinstance(ld.get("location"), dict) else {}
    city = ((loc.get("address") or {}).get("addressLocality") or card.get("city") or "").strip()
    if city.lower() not in SDQ:
        return None
    venue = (loc.get("name") or card.get("venue") or "").strip()
    title = clean_title(ld.get("name") or card.get("title") or "")
    desc = _description(ld.get("description") or "")
    cats = [c.lower() for c in card.get("cats", [])]
    category = next((CATS[c] for c in cats if c in CATS), None) or normalize_category(title, " ".join(cats), desc)
    is_free, pmin, pmax = _price(ld.get("offers"))
    end = None
    try:
        end = datetime.fromisoformat(str(ld.get("endDate"))).astimezone(TZ_SDQ).date() if ld.get("endDate") else None
    except ValueError:
        end = None
    dates = [start.date().isoformat()]
    if end and end > start.date():
        dates.append(end.isoformat())
    return Event(
        source="ticketmax",
        source_name="Ticketmax",
        url=card["url"],
        title=title,
        dates=dates,
        start_time=None if (start.hour, start.minute) == (0, 0) else start.strftime("%H:%M"),
        venue=venue,
        zone=zone_for(venue),
        category=category,
        is_free=is_free,
        price_min=pmin,
        price_max=pmax,
        kids=guess_kids(title, desc, " ".join(cats)),
        tags=["formacion"] if "conferencias" in cats else [],
        description=desc,
        ticket_url=card["url"],
    )


class Ticketmax(Source):
    id = "ticketmax"
    name = "Ticketmax"
    delay = 3.0
    default_max_details = 80

    def run(self) -> list[Event]:
        cards = parse_cards(self.fetcher.get(HOME, delay=self.delay).text)
        wanted = [c for c in cards if c["city"].lower() in SDQ and not SKIP_CATS & {x.lower() for x in c["cats"]}]
        # Primero las que aún no están en la base, para que un tope de páginas no deje fuera eventos nuevos.
        wanted.sort(key=lambda c: self.db.page_known(c["url"]))
        if self.max_details is not None:
            wanted = wanted[: self.max_details]
        self.log(f"[{self.id}] {len(cards)} eventos en la portada, {len(wanted)} de Santo Domingo por leer")
        out = []
        for card in wanted:
            html, fp, changed = self.fetch_page(card["url"])
            if not changed:
                continue
            ev = parse_event(card, html, self.today)
            if ev:
                out.append(ev)
            self.db.record_page(card["url"], fp, self.now)
        return out
