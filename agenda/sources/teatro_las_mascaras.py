"""Teatro Las Máscaras (teatrolasmascaras.com): cartelera en la portada, sitio de WordPress.com.

Qué se verificó (6 oct 2026, con la herramienta de lectura web, no con el HTML crudo):
  - robots.txt solo bloquea /wp-admin/, el login y rutas internas de WordPress.com; la portada se puede leer.
    La API pública de WordPress.com (public-api.wordpress.com) sí está bloqueada por robots: no se usa.
  - La portada lista cada montaje como un bloque con <h2> (título) y, debajo, en este orden:
        "Del 2 al 18 de Octubre, 2026"            (rango; a veces cruza de mes o no trae año)
        texto de la obra
        "Funciones: Viernes y Sábados 8:30 p.m. | Domingos 6:30 p.m."
        "🎟️ Boletas: RD$875 p/p"  ·  "Disponibles en Tix.do"
        "🚗 Parqueo en Plaza Colonial:" ... "2 primeras horas: RD$50" ... (OJO: no es precio de la entrada)
        botón "OBTEN TU BOLETA AQUI" -> https://tix.do/event/<slug>
  - Los montajes no tienen página propia: el enlace del evento es la portada con un ancla (#slug-del-titulo).
  - La página no trae dirección. Dice "la sala más acogedora de la Zona Colonial".
Qué NO se verificó: el HTML real. Los selectores salen del texto de la página, no del marcado, así que se trabaja
sobre las líneas de texto visible (como `jazz_en_dominicana`). Si cambia el formato, `python -m agenda inspect`.

Decisiones:
  - Las funciones son viernes y sábado a las 8:30 p. m. y domingo a las 6:30 p. m.: la hora no es una sola, así que
    `start_time` queda vacío (no se inventa) y el horario completo va en la descripción.
  - Rango sin sesiones: sale una vez con "Hasta" (dates = [inicio, fin]); no se inventan días de función.
  - Precio solo de la línea de boletas; el parqueo (RD$50 / RD$100) nunca cuenta como precio.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from agenda.dates import find_dates, parse_price, parse_time
from agenda.htmlutil import parse, text_lines
from agenda.models import Event, guess_kids
from agenda.sources.base import Source

BASE = "https://teatrolasmascaras.com/"
VENUE = "Teatro Las Máscaras"
MAX_DESCRIPTION = 280

_DATE_LINE = re.compile(r"^\s*del?\s+\d{1,2}\b", re.I)
_TICKET_LINE = re.compile(r"\b(boletas?|entradas?|precio|costo)\b", re.I)
_PARKING = re.compile(r"parqueo|estacionamiento|parking", re.I)
_SCHEDULE = re.compile(r"^\W*(funciones?|horarios?)\s*:", re.I)
_TIME_PM = re.compile(r"\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m", re.I)
_TICKET_TEXT = re.compile(r"boleta|entrada|tickets?", re.I)


class TeatroLasMascaras(Source):
    id = "teatro_las_mascaras"
    name = "Teatro Las Máscaras"
    delay = 3.0
    default_zone = "Ciudad Colonial"

    def run(self) -> list[Event]:
        html, fp, _ = self.fetch_page(BASE, force=True)
        events = parse_page(html, BASE, self.today)
        if not events:
            self.log(
                f"[{self.id}] 0 montajes vigentes. La cartelera pudo quedar vacía o la página cambió: "
                f"`python -m agenda inspect {BASE}` y revisa parse_page()."
            )
        self.db.record_page(BASE, fp, self.now)
        return events


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _blocks(lines: list[str], today: date) -> list[tuple[str, list[date], list[str]]]:
    """(título, fechas, líneas del bloque) por cada par 'título + línea de fechas'."""
    heads: list[tuple[int, str, list[date]]] = []
    for i in range(len(lines) - 1):
        if _DATE_LINE.match(lines[i + 1]) and not _DATE_LINE.match(lines[i]):
            dates = find_dates(lines[i + 1], today)
            if dates:
                heads.append((i, lines[i], dates))
    out = []
    for n, (i, title, dates) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out.append((title, dates, lines[i + 2 : end]))
    return out


def _price(body: list[str]) -> tuple[bool | None, int | None, int | None]:
    """Solo la línea de boletas. Sin ella, o sin monto, el precio queda por confirmar."""
    for ln in body:
        if _TICKET_LINE.search(ln) and not _PARKING.search(ln):
            res = parse_price(ln)
            if res[0] is not None:
                return res
    return None, None, None


def _schedule(body: list[str]) -> tuple[str | None, str]:
    """(hora única o None, texto del horario). Si hay horas distintas no se escoge una."""
    for ln in body:
        if _SCHEDULE.match(ln):
            times = {re.sub(r"[\s.]", "", t.lower()) for t in _TIME_PM.findall(ln)}
            text = re.sub(r"\s+", " ", ln).strip()
            if len(times) == 1:
                return parse_time(ln), text
            return None, text
    return None, ""


def _blurb(body: list[str]) -> str:
    for ln in body:
        if len(ln) > 60 and not _SCHEDULE.match(ln) and not _TICKET_LINE.search(ln) and not _PARKING.search(ln):
            return re.sub(r"\s+", " ", ln)
    return ""


def _ticket_links(tree) -> list[str]:
    links = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if "tix.do" in href and _TICKET_TEXT.search(a.text(strip=True)):
            links.append(href)
    return links


def _specific(url: str) -> bool:
    """Un enlace a la portada de la ticketera (tix.do/) no sirve como enlace de compra."""
    return bool(re.sub(r"^https?://[^/]+/?", "", url).strip("/"))


def parse_page(html: str, base_url: str, today: date) -> list[Event]:
    tree = parse(html)
    lines = text_lines(tree)
    blocks = _blocks(lines, today)
    links = _ticket_links(tree)
    use_links = len(links) == len(blocks)  # si no cuadran, mejor sin enlace que uno cruzado
    out: list[Event] = []
    for n, (title, dates, body) in enumerate(blocks):
        if dates[-1] < today:
            continue
        is_free, pmin, pmax = _price(body)
        start_time, schedule = _schedule(body)
        desc = " ".join(p for p in (schedule, _blurb(body)) if p)
        if len(desc) > MAX_DESCRIPTION:
            desc = desc[: MAX_DESCRIPTION - 1].rstrip() + "…"
        link = links[n] if use_links and _specific(links[n]) else ""
        out.append(
            Event(
                source=TeatroLasMascaras.id,
                source_name=TeatroLasMascaras.name,
                url=f"{base_url.rstrip('/')}/#{_slug(title)}",
                title=title,
                dates=[dates[0].isoformat(), dates[-1].isoformat()] if dates[0] != dates[-1] else [dates[0].isoformat()],
                start_time=start_time,
                venue=VENUE,
                zone=TeatroLasMascaras.default_zone,
                category="Teatro",
                is_free=is_free,
                price_min=pmin,
                price_max=pmax,
                kids=guess_kids(title),
                description=desc,
                ticket_url=link,
            )
        )
    return out
