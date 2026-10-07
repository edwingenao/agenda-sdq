"""Teatro Nacional Eduardo Brito (teatronacional.gob.do).

Qué se verificó (5 oct 2026, con la herramienta de lectura web):
  - Los eventos son un tipo de contenido propio de WordPress: /events/<slug>/.
  - La API REST pública /wp-json/wp/v2/event responde con id, link, title y event-category
    (pero NO con la fecha del evento: `date` es la de publicación).
  - La fecha, la sala y los precios salen en la página de detalle:
        "Fecha: 7 de octubre, 2026" · "Sala: Sala Carlos Piantini" · tabla "Platea RD$2,290.00"
  - No hay JSON-LD. El listado /events/ se rellena con JavaScript, por eso no se usa.
  - Categoría "Gratis" (id 18) existe en la taxonomía de eventos.
Qué NO se verificó: el HTML real de la página de detalle (los selectores salen de texto, no de marcado).
"""

from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

from agenda.dates import find_dates, parse_price, parse_time
from agenda.htmlutil import label_value, parse, text_lines
from agenda.http import Disallowed
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

BASE = "https://teatronacional.gob.do"
API = f"{BASE}/wp-json/wp/v2/event"
SITEMAP = f"{BASE}/wp-sitemap-posts-event-1.xml"

CATEGORIES = {
    23: "Comedia",
    22: "Conciertos",
    30: "Conferencia / Charla",
    17: "Danza",
    18: "Gratis",
    21: "Ópera / Lírica",
    29: "Proyección Audiovisual",
    19: "Teatro",
}
FREE_CATEGORY = 18


class TeatroNacional(Source):
    id = "teatro_nacional"
    name = "Teatro Nacional"
    delay = 2.0
    default_zone = "Plaza de la Cultura"

    # --- descubrimiento -------------------------------------------------
    def list_items(self) -> list[dict]:
        """Eventos con link, título y categorías. API REST primero; sitemap como respaldo."""
        try:
            items: list[dict] = []
            for page in range(1, 4):
                r = self.fetcher.get(
                    API,
                    delay=self.delay,
                    params={"per_page": 100, "page": page, "_fields": "id,link,title,event-category"},
                )
                batch = r.json()
                items.extend(batch)
                if len(batch) < 100:
                    break
            if items:
                return items
        except (Disallowed, ValueError, Exception) as e:  # noqa: BLE001 - cualquier fallo -> respaldo
            self.log(f"[{self.id}] API REST no disponible ({e}); uso el sitemap")
        xml = self.fetcher.get(SITEMAP, delay=self.delay).text
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ElementTree.fromstring(xml)
        return [{"link": loc.text.strip()} for loc in root.findall(".//s:loc", ns) if loc.text]

    # --- ejecución -------------------------------------------------------
    def run(self) -> list[Event]:
        events: list[Event] = []
        items = self.list_items()
        self.log(f"[{self.id}] {len(items)} eventos en el listado")
        for item in items:
            url = item["link"]
            try:
                html, fp, changed = self.fetch_page(url)
            except Disallowed as e:
                self.log(f"[{self.id}] omitido: {e}")
                continue
            if not changed:
                continue
            ev = parse_detail(html, url, item, self.today)
            if ev is None:
                ev = self.llm_event(url, text_lines(parse(html)))
            if ev is None:
                self.log(f"[{self.id}] no pude extraer fecha de {url} (revisar con `inspect`)")
                continue
            self.db.record_page(url, fp, self.now)
            if ev.end < self.today.isoformat():
                continue  # evento pasado
            events.append(ev)
        return events


def parse_detail(html: str, url: str, item: dict, today) -> Event | None:
    tree = parse(html)
    lines = text_lines(tree)

    h1 = tree.css_first("h1")
    rendered = (item.get("title") or {}).get("rendered", "") if isinstance(item.get("title"), dict) else ""
    title = (h1.text(strip=True) if h1 else "") or htmllib.unescape(rendered) or url.rstrip("/").split("/")[-1]

    review = False
    fecha = label_value(lines, "Fecha", "Fechas")
    dates = find_dates(fecha, today) if fecha else []
    if not dates:
        review = True
        dates = find_dates("\n".join(lines[:80]), today)
    if not dates:
        return None

    hora = label_value(lines, "Hora", "Horario", "Hora de inicio")
    start_time = parse_time(hora) if hora else None

    sala = label_value(lines, "Sala", "Lugar")
    if sala and "teatro nacional" not in sala.lower():
        venue = f"{sala}, Teatro Nacional"
    else:
        venue = sala or "Teatro Nacional Eduardo Brito"

    price_text = "\n".join(ln for ln in lines if re.search(r"RD\s*\$", ln))
    is_free, pmin, pmax = parse_price(price_text)
    cat_ids = item.get("event-category") or []
    if FREE_CATEGORY in cat_ids:
        if is_free is False:
            review = True  # categoría "Gratis" pero con precios: contradictorio
        else:
            is_free, pmin, pmax = True, 0, 0

    cat_names = [CATEGORIES[c] for c in cat_ids if c in CATEGORIES and c != FREE_CATEGORY]
    page_cat = label_value(lines, "Categoría", "Categoria") or ""  # "Conciertos", "Danza"...
    category = normalize_category(*cat_names, page_cat, title)

    ticket = ""
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if "boleteria.com.do" in href:
            ticket = href
            break

    desc = ""
    for p in tree.css("p"):
        t = p.text(strip=True)
        if len(t) >= 60:
            desc = t[:280]
            break

    return Event(
        source="teatro_nacional",
        source_name="Teatro Nacional",
        url=url,
        title=title,
        dates=[d.isoformat() for d in dates],
        start_time=start_time,
        venue=venue,
        zone=zone_for(venue, "Plaza de la Cultura"),
        category=category,
        is_free=is_free,
        price_min=pmin,
        price_max=pmax,
        kids=guess_kids(title, desc),
        tags=[],
        description=desc,
        ticket_url=ticket,
        needs_review=review,
    )


def _unused(url: str) -> str:  # pragma: no cover
    return urlparse(url).path
