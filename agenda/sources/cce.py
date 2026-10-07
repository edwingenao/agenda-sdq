"""Centro Cultural de España en Santo Domingo (ccesd.aecid.es).

Qué se verificó (5 oct 2026):
  - Portal Liferay. El buscador (/eventos/buscador-de-eventos) lista tarjetas con título (enlace a /w/<slug>),
    fechas y categoría; NO muestra lugar ni precio. Tiene 172 páginas y filtros "Fecha desde/hasta".
  - La página de detalle sí trae: categoría ("Formación"), precio ("Gratuito (Entrada libre hasta completar
    aforo)"), fechas como "17/Oct/2026 24/Oct/2026 31/Oct/2026 07/Nov/2026", horario ("10 am a 1 pm"),
    lugar ("Centro Cultural de España") y cierre de inscripciones. No hay JSON-LD.
  - robots.txt: prohíbe /busqueda, /search, /user/, /group/, /web/guest/, /c/ y cualquier URL con
    `p_p_id=` o `p_auth=` (la paginación de Liferay suele usarlos), y pide Crawl-delay 30 a los
    rastreadores de IA. Por eso: solo la primera página del listado, detalle de a pocos eventos por
    corrida y 30 s entre peticiones, aunque el delay no nos aplique estrictamente.
Verificado contra el HTML real del buscador (samples/): tarjetas `.cardReco` con `a.title`, `.fecha-rango`, `a.cat-reco`.
La página 1 mezcla eventos pasados y futuros; se descartan los pasados por la fecha de la tarjeta.
"""

from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse

from agenda.dates import find_dates, parse_price, parse_time
from agenda.htmlutil import label_value, parse, text_lines
from agenda.http import Disallowed
from agenda.models import Event, guess_kids, normalize_category
from agenda.sources.base import Source

LIST_URL = "https://ccesd.aecid.es/eventos/buscador-de-eventos"
VENUE = "Centro Cultural de España"
_SKIP_LINE = re.compile(r"inscripci|cierre|plazo", re.I)
_END_MARK = re.compile(r"relacionad|te puede interesar|pr[oó]ximos eventos|compartir", re.I)
_FORMACION = re.compile(r"\b(taller|curso|clase|formaci[oó]n|seminario|diplomado)", re.I)
_CATEGORY_WORDS = re.compile(
    r"^(Formaci[oó]n|Letras|M[uú]sica(?: / Sonido)?|Cine(?: / Audiovisual)?|Artes? Visuales|Exposiciones?|"
    r"Artes? Esc[eé]nicas?|Teatro|Danza|Patrimonio|Debates?)$",
    re.I,
)


class CentroCulturalEspana(Source):
    id = "cce"
    name = "Centro Cultural de España"
    delay = 30.0
    default_zone = "Ciudad Colonial"
    default_max_details = 12  # detalle por corrida: 12 x 30 s = 6 min

    def run(self) -> list[Event]:
        html = self.fetcher.get(LIST_URL, delay=self.delay).text
        cards = parse_cards(html, LIST_URL, self.today)
        links = [c["url"] for c in cards] or extract_links(html, LIST_URL)
        # La tarjeta ya trae las fechas: no gastar 30 s en eventos que ya terminaron.
        past = {c["url"] for c in cards if c["dates"] and max(c["dates"]) < self.today.isoformat()}
        links = [u for u in links if u not in past]
        self.log(f"[{self.id}] {len(links)} eventos vigentes en la página 1 del buscador ({len(past)} ya pasaron)")
        # Primero los que nunca hemos visto; luego el resto, hasta el límite por corrida.
        links = sorted(links, key=lambda u: self.db.page_known(u))[: self.max_details]
        events: list[Event] = []
        for url in links:
            try:
                page, fp, changed = self.fetch_page(url)
            except Disallowed as e:
                self.log(f"[{self.id}] omitido: {e}")
                continue
            if not changed:
                continue
            ev = parse_detail(page, url, self.today)
            if ev is None:
                ev = self.llm_event(url, text_lines(parse(page)))
            if ev is None:
                self.log(f"[{self.id}] no pude extraer fechas de {url} (revisar con `inspect`)")
                continue
            self.db.record_page(url, fp, self.now)
            if ev.end < self.today.isoformat():
                continue
            events.append(ev)
        return events


def parse_cards(html: str, base_url: str, today) -> list[dict]:
    """Tarjetas del buscador (`.cardReco`): enlace /w/, título, categorías y fechas "06/Oct/2026"."""
    tree = parse(html)
    out: dict[str, dict] = {}
    for card in tree.css(".cardReco"):
        a = card.css_first("a.title[href]")
        if a is None:
            continue
        href = urldefrag(urljoin(base_url, a.attributes.get("href") or ""))[0]
        if not urlparse(href).path.startswith("/w/") or "p_p_id=" in href:
            continue
        dates = find_dates(" ".join(n.text(strip=True) for n in card.css(".fecha-rango")), today, only_slash=True)
        out.setdefault(
            href,
            {
                "url": href,
                "title": a.text(strip=True),
                "cats": [c.text(strip=True) for c in card.css("a.cat-reco")],
                "dates": [d.isoformat() for d in dates],
            },
        )
    return list(out.values())


def extract_links(html: str, base_url: str) -> list[str]:
    tree = parse(html)
    seen: dict[str, None] = {}
    for a in tree.css("a[href]"):
        href = urldefrag(urljoin(base_url, a.attributes.get("href") or ""))[0]
        p = urlparse(href)
        if p.netloc == urlparse(base_url).netloc and p.path.startswith("/w/") and "p_p_id=" not in href:
            seen.setdefault(href, None)
    return list(seen)


def _main_lines(lines: list[str], title: str) -> list[str]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == title.strip()), 0)
    out: list[str] = []
    for ln in lines[start : start + 120]:
        if out and _END_MARK.search(ln):
            break
        out.append(ln)
    return out


def parse_detail(html: str, url: str, today) -> Event | None:
    tree = parse(html)
    all_lines = text_lines(tree)
    h1 = tree.css_first("h1")
    title = h1.text(strip=True) if h1 else ""
    if not title:
        return None
    lines = [ln for ln in _main_lines(all_lines, title) if not _SKIP_LINE.search(ln)]
    body = "\n".join(lines)

    review = False
    dates = find_dates(body, today, only_slash=True)
    if not dates:
        review = True
        dates = find_dates(body, today)
    if not dates:
        return None
    if len(dates) > 12:
        review = True  # demasiadas fechas: seguramente mezcla contenido relacionado

    hora_line = next((ln for ln in lines if re.search(r"\d\s*(?:[ap]\.?\s*m\b|:\d{2})", ln, re.I)), "")
    start_time = parse_time(label_value(lines, "Horario", "Hora") or hora_line) if (hora_line or lines) else None

    venue = label_value(lines, "Lugar", "Sede", "Espacio") or VENUE
    price_blob = "\n".join(
        ln for ln in lines if re.search(r"gratuit|gratis|entrada libre|precio|costo|coste|cuota|RD\s*\$|\$", ln, re.I)
    )
    is_free, pmin, pmax = parse_price(price_blob)

    cat_label = next((ln for ln in lines[:15] if _CATEGORY_WORDS.match(ln)), "")
    category = normalize_category(cat_label, title)
    tags = ["formacion"] if (re.match(r"formaci", cat_label, re.I) or _FORMACION.search(title)) else []

    desc = ""
    for p in tree.css("p"):
        t = p.text(strip=True)
        if len(t) >= 60:
            desc = t[:280]
            break

    return Event(
        source="cce",
        source_name="Centro Cultural de España",
        url=url,
        title=title,
        dates=[d.isoformat() for d in dates],
        start_time=start_time,
        venue=venue,
        zone="Ciudad Colonial",
        category=category,
        is_free=is_free,
        price_min=pmin,
        price_max=pmax,
        kids=guess_kids(title, desc),
        tags=tags,
        description=desc,
        needs_review=review,
    )
