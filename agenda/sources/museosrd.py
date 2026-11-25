"""Red Nacional de Museos de la República Dominicana (museosrd.gob.do): eventos de los museos.

Verificado el 24 nov 2026 desde la PC (navegador de la app de escritorio):
  - robots.txt solo bloquea /wp-content/plugins/. El sitemap_index.xml (Rank Math) lista job_listing-sitemap.xml, donde
    cada evento es /evento/<slug>/ con <lastmod> (también hay /museos/, /recorridos-virtuales/ y /pieza/: se ignoran).
    Unos 20 eventos en total; los de 2024 y 2025 siguen en el sitemap, así que se filtra por fecha.
  - Cada página de evento trae, en texto, "Fecha: Sábado 28 de noviembre de 2026.", "Hora: 6:00 p. m.", "Lugar: ...",
    "Dirección: ... Ciudad Colonial, Santo Domingo ..." y a veces "Entrada: Libre, hasta completar aforo.".
    Sin "Entrada" el precio queda por confirmar. Incluye museos de otras ciudades (Centro León en Santiago, Puerto Plata,
    La Romana...): se descartan. Es WordPress con tema My Listing (tipo de contenido job_listing).
  - SIN HTML REAL VERIFICADO: no se pudo bajar el HTML crudo (el shell no llega al sitio y la herramienta del navegador no
    devolvió el DOM). Las muestras de samples/museosrd_*.txt son el texto visible de dos páginas reales; el adaptador
    trabaja sobre las líneas de texto, no sobre selectores. En la primera corrida real hay que comprobar que
    `text_lines` del HTML produce las mismas líneas "Fecha:", "Hora:"... Los teléfonos de la muestra se quitaron.
  - No se leyeron los términos de uso del sitio.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from agenda.dates import find_dates, parse_price, parse_time
from agenda.htmlutil import label_value, parse, text_lines
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

SITEMAP = "https://museosrd.gob.do/job_listing-sitemap.xml"
MAX_DESCRIPTION = 280
RECENT_DAYS = 120  # páginas editadas hace más que esto son de eventos viejos: no se piden
SD = re.compile(r"santo domingo|distrito nacional|ciudad colonial", re.I)
OTHER_CITY = re.compile(
    r"santiago|puerto plata|la romana|altos de chav[oó]n|tamboril|salcedo|higüey|higuey|punta cana|san pedro|la vega|"
    r"jarabacoa|constanza|moca|bonao|samaná|samana|barahona|monte cristi|san francisco de macor[ií]s",
    re.I,
)
LABEL_LINE = re.compile(r"^(fecha|hora|lugar|direcci[oó]n|entrada|informaci[oó]n|costo|precio)\s*:", re.I)
SKIP_LINE = re.compile(r"evento comienza|informaci[oó]n de la actividad|detalles de la actividad|^detalles$", re.I)
FREE = re.compile(r"\b(libre|gratis|gratuit[oa]s?|sin costo)\b", re.I)


def sitemap_urls(xml: str, today: date) -> list[str]:
    """URLs /evento/ del sitemap editadas en los últimos RECENT_DAYS días (las sin <lastmod> también)."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", block)
        mod = re.search(r"<lastmod>(\d{4}-\d{2}-\d{2})", block)
        if not loc or "/evento/" not in loc.group(1):
            continue
        if mod and date.fromisoformat(mod.group(1)) < today - timedelta(days=RECENT_DAYS):
            continue
        out.append(loc.group(1).strip())
    return out


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().rstrip(".").strip()


def parse_lines(title: str, lines: list[str], url: str, today: date) -> Event | None:
    """Evento a partir del título y las líneas de texto visibles de su página."""
    when = label_value(lines, "Fecha")
    if not title or not when:
        return None
    dates = find_dates(when, today)
    if not dates or dates[-1] < today:
        return None
    venue = _clean(label_value(lines, "Lugar"))
    address = _clean(label_value(lines, "Dirección", "Direccion"))
    place = f"{venue} {address}"
    needs_review = False
    if SD.search(place):
        pass
    elif OTHER_CITY.search(place):
        return None  # museo de otra ciudad: solo Santo Domingo
    else:
        needs_review = True  # no se sabe dónde es: se publica marcado para revisión
    entry = _clean(label_value(lines, "Entrada", "Costo", "Precio"))
    is_free, pmin, pmax = (None, None, None)
    if entry:
        is_free, pmin, pmax = parse_price(entry)
        if is_free is None and FREE.search(entry):
            is_free, pmin, pmax = True, 0, 0
    intro = [ln for ln in lines if len(ln) > 60 and not LABEL_LINE.match(ln) and not SKIP_LINE.search(ln)]
    desc = re.sub(r"\s+", " ", intro[0]) if intro else ""
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[: MAX_DESCRIPTION - 1].rstrip() + "…"
    return Event(
        source="museosrd",
        source_name="Red Nacional de Museos",
        url=url,
        title=_clean(title),
        dates=[dates[0].isoformat(), dates[-1].isoformat()] if dates[-1] > dates[0] else [dates[0].isoformat()],
        start_time=parse_time(label_value(lines, "Hora") or ""),
        venue=venue or address,
        zone=zone_for(venue) or zone_for(address),
        category=normalize_category(title, desc),
        is_free=is_free,
        price_min=pmin,
        price_max=pmax,
        kids=guess_kids(title, desc),
        description=desc,
        needs_review=needs_review,
    )


def parse_page(html: str, url: str, today: date) -> Event | None:
    tree = parse(html)
    h1 = tree.css_first("h1")
    title = h1.text(strip=True) if h1 else ""
    if not title and tree.css_first("title"):
        title = tree.css_first("title").text(strip=True).split("|")[0]
    return parse_lines(title, text_lines(tree), url, today)


class MuseosRD(Source):
    id = "museosrd"
    name = "Red Nacional de Museos"
    delay = 3.0
    default_max_details = 30

    def run(self) -> list[Event]:
        urls = sitemap_urls(self.fetcher.get(SITEMAP, delay=self.delay).text, self.today)
        urls.sort(key=self.db.page_known)  # primero las que no están en la base
        if self.max_details is not None:
            urls = urls[: self.max_details]
        out = []
        for url in urls:
            html, fp, changed = self.fetch_page(url)
            if not changed:
                continue
            ev = parse_page(html, url, self.today)
            if ev:
                out.append(ev)
            self.db.record_page(url, fp, self.now)
        self.log(f"[{self.id}] {len(urls)} páginas recientes en el sitemap, {len(out)} eventos próximos nuevos o cambiados")
        return out
