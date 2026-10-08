"""Jazz en Dominicana (jazzendominicana.com): blog de Blogger, feed Atom.

Verificado el 5 oct 2026 con el navegador: GET /feeds/posts/default?max-results=N devuelve Atom estándar
(<entry> con <published>, <title>, <link rel='alternate'> y <content type='html'> COMPLETO).
Cada semana hay una entrada "Jazz en Vivo en RD del 4 al 10 de octubre" con un bloque por concierto:

    Jueves 8: Sandy Gabriel Jazz Residence
    at The Green Room (Santo Domingo):
    ...texto libre con hora ("a las 9:30PM"), precio ("Cover de $250", "RD$1,500.00"), lugar...

El encabezado puede ocupar varias líneas y termina en "(Ciudad):". La fecha completa se deduce de
"día de la semana + número" cerca de la fecha de publicación. Solo se conserva Santo Domingo.
Las entradas que no son semanales (anuncios de festivales) van al extractor con IA si está activo.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from agenda.dates import parse_price
from agenda.htmlutil import parse, text_lines
from agenda.models import Event, zone_for
from agenda.sources.base import Source

FEED = "https://www.jazzendominicana.com/feeds/posts/default?max-results=10"
NS = {"a": "http://www.w3.org/2005/Atom"}
DAYS = {"lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6}
HEAD = re.compile(
    r"(?P<dow>Lunes|Martes|Mi[eé]rcoles|Jueves|Viernes|S[aá]bado|Domingo)\s+(?P<day>\d{1,2})\s*:\s*"
    r"(?P<title>[^()]{3,200}?)\((?P<city>[^()]{3,30})\)\s*:",
    re.I | re.S,
)
CITY_OK = ("santo domingo",)
VENUES = [  # el texto libre rara vez marca el lugar de forma uniforme: lista de lugares conocidos
    "The Green Room",
    "Dominican Fiesta Hotel & Casino",
    "Teatro Nacional",
    "Casa de Teatro",
    "Plaza Montesinos",
    "Jazz Café",
    "Hotel Embajador",
]
_NO_COVER_SERIES = re.compile(r"fiesta sunset jazz", re.I)
_TIME = re.compile(r"(?:a las|a partir de las|desde las)\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m", re.I)
_ANY_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b", re.I)


def _hhmm(m: re.Match) -> str:
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if ap == "p" and h < 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def resolve_date(dow: str, day: int, published: date) -> date | None:
    """La fecha cuyo número y día de la semana coinciden, entre 3 días antes y 21 después de publicar."""
    wd = DAYS[dow.lower()]
    for off in range(-3, 22):
        d = published + timedelta(days=off)
        if d.day == day and d.weekday() == wd:
            return d
    return None


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip(" -–:")


def parse_weekly(title_text: str, lines: list[str], published: date, post_url: str, today: date) -> tuple[list[Event], int]:
    """(eventos de Santo Domingo, bloques de otras ciudades descartados)."""
    text = "\n".join(lines)
    heads = list(HEAD.finditer(text))
    out: list[Event] = []
    skipped = 0
    for i, h in enumerate(heads):
        body = text[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        if not any(c in h["city"].lower() for c in CITY_OK):
            skipped += 1
            continue
        d = resolve_date(h["dow"], int(h["day"]), published)
        if d is None or d < today:
            continue
        raw_title = _clean(h["title"])
        m_at = re.search(r"\s(?:at|en)\s+(?:el\s+)?(.+)$", raw_title)
        head_venue = _clean(m_at.group(1)) if m_at else ""
        title = _clean(raw_title[: m_at.start()]) if m_at else raw_title
        venue = next((v for v in VENUES if v.lower() in (head_venue + " " + body).lower()), head_venue)

        tm = _TIME.search(body) or _ANY_TIME.search(body)
        # "No cover" + boletas a RD$1,500: manda el monto
        is_free, pmin, pmax = parse_price(body)
        if is_free is None and re.search(r"\bno cover\b|entrada libre|gratis", body, re.I):
            is_free, pmin, pmax = True, 0, 0
        if is_free is None and _NO_COVER_SERIES.search(title):
            # Su entrada del feed no dice el precio, pero la barra lateral del blog la lista con "No cover!"
            # (el feed no la trae) y Edwin lo confirmó el 7 de octubre de 2026.
            is_free, pmin, pmax = True, 0, 0
        slug = re.sub(r"\W+", "-", title.casefold()).strip("-")[:50]
        out.append(
            Event(
                source="jazz_en_dominicana",
                source_name="Jazz en Dominicana",
                url=f"{post_url}#{d.isoformat()}-{slug}",
                title=title,
                dates=[d.isoformat()],
                start_time=_hhmm(tm) if tm else None,
                venue=venue,
                zone=zone_for(venue, ""),
                category="Música",
                is_free=is_free,
                price_min=pmin,
                price_max=pmax if pmax != pmin else None,
                tags=["jazz"],
                description=_clean(body)[:280],
                needs_review=not venue,
            )
        )
    return out, skipped


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    entries = []
    for e in root.findall("a:entry", NS):
        link = next((l.get("href") for l in e.findall("a:link", NS) if l.get("rel") == "alternate"), "")
        pub = (e.findtext("a:published", default="", namespaces=NS) or "")[:10]
        entries.append(
            {
                "title": e.findtext("a:title", default="", namespaces=NS) or "",
                "url": link,
                "published": date.fromisoformat(pub) if pub else None,
                "html": e.findtext("a:content", default="", namespaces=NS) or "",
            }
        )
    return entries


class JazzEnDominicana(Source):
    id = "jazz_en_dominicana"
    name = "Jazz en Dominicana"
    delay = 3.0

    def run(self) -> list[Event]:
        xml_text = self.fetcher.get(FEED, delay=self.delay).text
        events: list[Event] = []
        for ent in parse_feed(xml_text):
            if not ent["published"] or not ent["url"]:
                continue
            if (self.today - ent["published"]).days > 45:
                continue
            lines = text_lines(parse(f"<body>{ent['html']}</body>"))
            if re.search(r"jazz en vivo en rd", ent["title"], re.I):
                evs, skipped = parse_weekly(ent["title"], lines, ent["published"], ent["url"], self.today)
                self.log(f"[{self.id}] «{ent['title']}»: {len(evs)} en Santo Domingo, {skipped} de otras ciudades")
                events += evs
            else:  # anuncios sueltos (festivales): solo con IA, y quedan para revisión
                ev = self.llm_event(ent["url"], lines)
                if ev:
                    ev.tags = sorted(set(ev.tags + ["jazz"]))
                    events.append(ev)
        return events
