"""zonacolonial.do/actividades — agenda de la Ciudad Colonial.

Qué se verificó (5 oct 2026): es WordPress + Elementor; robots.txt permite todo salvo /feed/;
no hay API de eventos (/wp-json/ no expone rutas de actividades) ni JSON-LD. La lista (~11 eventos,
sin paginación) muestra por tarjeta: título (enlace), fecha tipo "OCT 06", recinto + dirección y
"Entrada Gratis" o monto. Sin año; la hora está solo en el botón "Agendar" (data-time).
Verificado contra el HTML real (samples/zonacolonial.html, 11 tarjetas). No hay selectores CSS fijos: se localiza cada tarjeta
buscando el ancestro más pequeño de un enlace que contenga exactamente UNA fecha "MES DD".
Si la página cambia o devuelve 0 tarjetas, corre `python -m agenda inspect <url>` y ajusta aquí.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urldefrag, urljoin, urlparse

from agenda.dates import month_day, parse_price
from agenda.htmlutil import parse
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

LIST_URL = "https://zonacolonial.do/actividades/"
DATE_TOKEN = re.compile(r"\b(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\s*(\d{1,2})\b", re.I)
BLOCK = {"agendar", "ver mapa", "ver más", "ver mas", "leer más", "leer mas", "más info", "más información"}
KNOWN_VENUES = [
    "Casa de Teatro",
    "Quinta Dominica",
    "Academia Dominicana de la Lengua",
    "Centro Cultural Taíno Casa del Cordón",
    "Museo de la Catedral",
    "Centro Cultural Banreservas",
    "Centro Cultural de España",
    "Plaza de España",
]


class ZonaColonial(Source):
    id = "zona_colonial"
    name = "Zona Colonial"
    delay = 3.0
    default_zone = "Ciudad Colonial"

    def run(self) -> list[Event]:
        html, fp, _ = self.fetch_page(LIST_URL, force=True)
        events = parse_listing(html, LIST_URL, self.today)
        if not events:
            self.log(
                f"[{self.id}] 0 tarjetas. La página pudo cambiar: "
                f"`python -m agenda inspect {LIST_URL}` y revisa parse_listing()."
            )
        self.db.record_page(LIST_URL, fp, self.now)
        return events


def _norm(t: str) -> str:
    return re.sub(r"\W+", "", t.casefold())


def card_times(tree) -> dict[tuple[str, str], str]:
    """El botón "Agendar" lleva data-title / data-date / data-time ("19:00"): ahí está la hora."""
    out: dict[tuple[str, str], str] = {}
    for b in tree.css("[data-date][data-title]"):
        t = (b.attributes.get("data-time") or "").strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", t):
            out[(b.attributes["data-date"], _norm(b.attributes["data-title"]))] = t.zfill(5)
    return out


def parse_listing(html: str, base_url: str, today) -> list[Event]:
    tree = parse(html)
    times = card_times(tree)
    host = urlparse(base_url).netloc
    cards: dict[str, dict] = {}

    for a in tree.css("a[href]"):
        href = urldefrag(urljoin(base_url, a.attributes.get("href") or ""))[0]
        if urlparse(href).netloc != host or href.rstrip("/") == base_url.rstrip("/"):
            continue
        label = a.text(strip=True)
        if len(label) < 3:
            continue
        node, card_text = a.parent, None
        for _ in range(6):
            if node is None:
                break
            text = node.text(separator="\n", strip=True)
            n = len(DATE_TOKEN.findall(text))
            if n == 1:
                card_text = text
                break
            if n > 1:
                break
            node = node.parent
        if not card_text:
            continue
        key = hashlib.sha1(card_text.encode()).hexdigest()
        cards.setdefault(key, {"text": card_text, "anchors": []})["anchors"].append((label, href))

    by_url: dict[str, Event] = {}
    for c in cards.values():
        anchors = [x for x in c["anchors"] if x[0].lower() not in BLOCK]
        if not anchors:
            continue
        title, url = max(anchors, key=lambda x: len(x[0]))
        text = c["text"]
        m = DATE_TOKEN.search(text)
        dt = month_day(m.group(1), m.group(2), today)
        if dt is None or dt < today:
            continue

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        venue = next((v for v in KNOWN_VENUES if v.lower() in text.lower()), "")
        if not venue:
            for ln in lines:
                if ln == title or DATE_TOKEN.fullmatch(ln) or ln.lower() in BLOCK:
                    continue
                if parse_price(ln)[0] is not None:
                    continue
                venue = ln
                break
        is_free, pmin, pmax = parse_price(text)  # "$1200" se asume RD$
        other = " ".join(ln for ln in lines if ln != venue and not venue.startswith(ln))
        category = normalize_category(title, other.replace(venue, ""))

        if url in by_url:  # misma actividad en varias fechas -> una sola entrada
            ev = by_url[url]
            if dt.isoformat() not in ev.dates:
                ev.dates = sorted(ev.dates + [dt.isoformat()])
            continue
        by_url[url] = Event(
            source="zona_colonial",
            source_name="Zona Colonial",
            url=url,
            title=title,
            dates=[dt.isoformat()],
            start_time=times.get((dt.isoformat(), _norm(title))),
            venue=venue,
            zone=zone_for(venue, "Ciudad Colonial"),
            category=category,
            is_free=is_free,
            price_min=pmin,
            price_max=pmax,
            kids=guess_kids(title),
        )
    return list(by_url.values())
