"""Fundación Sinfonía (sinfonia.org.do): agenda de la Orquesta Sinfónica Nacional y conciertos asociados.

Verificado el 7 oct 2026 desde la PC:
  - robots.txt solo bloquea un JSON de un plugin; publica sitemap_index.xml. Los eventos están en
    /evento-sitemap.xml (40 en total, uno o dos al mes; cada <url> con <lastmod>).
  - Cada /agenda/<slug>/ trae: `.cont-date` con fecha y hora ("4 de noviembre de 2026, 8:30 p.m."), el título en
    <h1>, campos `.info-item` (Etiquetas, Modalidad, Tipo, Ubicación; el valor en `.fs-24`) y el texto en
    `.wp-block-paragraph` / `.wp-block-list li`, donde van los precios ("Platea: 5,640.00 y 3,405.00") o "Entradas
    libres de costo". No hay JSON-LD de evento. El botón de compra es un enlace de WhatsApp: no se usa.
  - "Temporada Sinfónica 2026" (Etiquetas: Temporada) abarca conciertos que tienen su propia página: se omite.

Por qué vale la pena aunque sea poco volumen: sus conciertos suelen ser en el Teatro Nacional, cuya página no publica la
hora; esta sí, y el precio. Al unir repetidos, la hora sale de aquí.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from agenda.dates import find_dates, parse_time
from agenda.htmlutil import parse
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

SITEMAP = "https://sinfonia.org.do/evento-sitemap.xml"
MAX_DESCRIPTION = 280
RECENT_DAYS = 200  # páginas editadas hace más que esto son de eventos viejos: no se piden
FREE = re.compile(r"\b(gratis|gratuit[oa]s?|entrada libre|libres? de costo|sin costo)\b", re.I)
# Montos en pesos ("5,640.00", "800"); no un año escrito como fecha ("1 de junio de 2026").
AMOUNT = re.compile(r"(?<![\d,.])(?<!de )(\d{1,3}(?:,\d{3})+|\d{3,6})(?:\.\d{2})?(?![\d,])")
PRICE_LINE = re.compile(r"\b(platea|balc[oó]n|general|boletas?|entradas?|precio|vip|palco|rd\$)", re.I)


def sitemap_urls(xml: str, today: date) -> list[str]:
    """URLs de eventos del sitemap editadas en los últimos RECENT_DAYS días (las sin <lastmod> también)."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", block)
        mod = re.search(r"<lastmod>(\d{4}-\d{2}-\d{2})", block)
        if not loc or "/agenda/" not in loc.group(1):
            continue
        if mod and date.fromisoformat(mod.group(1)) < today - timedelta(days=RECENT_DAYS):
            continue
        out.append(loc.group(1).strip())
    return out


def _price(lines: list[str]) -> tuple[bool | None, int | None, int | None]:
    amounts = []
    for ln in lines:
        if PRICE_LINE.search(ln):
            amounts += [int(a.replace(",", "")) for a in AMOUNT.findall(ln)]
    amounts = [a for a in amounts if a >= 100]  # fuera años de una sola cifra, horas, etc.
    if amounts:
        lo, hi = min(amounts), max(amounts)
        return False, lo, hi if hi > lo else None
    if any(FREE.search(ln) for ln in lines):
        return True, 0, None
    return None, None, None


def parse_page(html: str, url: str, today: date) -> Event | None:
    tree = parse(html)
    when = tree.css_first(".cont-date")
    h1 = tree.css_first("h1")
    if not when or not h1:
        return None
    info = {}
    for item in tree.css(".info-item"):
        label, value = item.css_first("h5"), item.css_first(".fs-24")
        if label and value:
            info[label.text(strip=True).lower()] = value.text(strip=True)
    if "temporada" in info.get("etiquetas", "").lower():
        return None  # paraguas de conciertos que tienen su propia página
    if info.get("modalidad", "").lower() == "virtual":
        return None
    when_text = when.text(strip=True)
    dates = find_dates(when_text, today)
    if not dates or dates[-1] < today:
        return None
    lines = [n.text(separator=" ", strip=True) for n in tree.css(".wp-block-paragraph, .wp-block-list li")]
    lines = [re.sub(r"\s+", " ", ln) for ln in lines if ln]
    is_free, pmin, pmax = _price(lines)
    title = re.sub(r"\s+", " ", h1.text(strip=True))
    venue = info.get("ubicación") or info.get("ubicacion") or ""
    desc = next((ln for ln in lines if len(ln) > 60 and not PRICE_LINE.search(ln)), "")
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[: MAX_DESCRIPTION - 1].rstrip() + "…"
    kind = " ".join(info.get(k, "") for k in ("etiquetas", "tipo"))
    category = "Música" if re.search(r"concierto|gala|recital", kind, re.I) else normalize_category(title, kind, desc)
    return Event(
        source="fundacion_sinfonia",
        source_name="Fundación Sinfonía",
        url=url,
        title=title,
        dates=[dates[0].isoformat(), dates[-1].isoformat()] if dates[-1] > dates[0] else [dates[0].isoformat()],
        start_time=parse_time(when_text),
        venue=venue,
        zone=zone_for(venue),
        category=category,
        is_free=is_free,
        price_min=pmin,
        price_max=pmax,
        kids=guess_kids(title, desc),
        description=desc,
    )


class FundacionSinfonia(Source):
    id = "fundacion_sinfonia"
    name = "Fundación Sinfonía"
    delay = 3.0
    default_max_details = 40

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
