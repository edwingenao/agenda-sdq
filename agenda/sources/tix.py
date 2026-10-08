"""TIX (tix.do): ticketera dominicana. Su sitio (Angular) lee la cartelera de una API Strapi pública.

Verificado el 7 oct 2026 desde la PC, con el navegador (pestaña de red):
  - tix.do no tiene robots.txt (sirve la misma página para cualquier ruta) y el de api.tix.do tiene todo comentado.
    Sus términos de uso (/terminos-de-uso) son solo los del comprador de boletas: no dicen nada sobre leer el sitio.
  - La cartelera sale de GET https://api.tix.do/api/events?filters[status]=active&filters[end_at][$gte]=<ahora>
    &sort[0]=start_at&pagination[pageSize]=100 (Strapi v4: data[].attributes). 180 eventos activos, en 2 páginas.
  - `start_at` / `end_at` en UTC son la función: Sandy Gabriel en The Green Room, 8 oct 9:30 p. m.; el Festival de
    Teatro Joven sale una vez por fin de semana. Los segundos son aleatorios (vienen del formulario del organizador).
    Las residencias largas (Pavel Núñez, hasta diciembre) vienen como un solo rango cuyo inicio es el de la venta.
  - No trae ciudad (solo `place`, el nombre de la sala) ni precio (solo `free`); el precio sale de otra llamada del
    flujo de compra, que no se usa.
  - OJO: sin `fields`, la API devuelve `vendor_account` con el correo personal del organizador. Aquí se piden solo
    los campos necesarios, así que esos datos ni llegan.
  - Hay otra API (api.v3.tix.do/events/public/list) con precio, pero solo 14 eventos y sin ciudad: no se usa.

Reglas: rango de varios días = sin hora (no se inventa); `free` true = gratis, false = de pago con monto por confirmar;
salas conocidas de Santo Domingo se publican; las de otras ciudades se descartan y las desconocidas tampoco se
publican: la corrida las lista para agregarlas a SDQ_PLACES (eran muchas: bares, iglesias, piscinas, fuera de la ciudad);
fuera Deporte, Wellness y Crecimiento Personal. Enlace: https://tix.do/event/<slug>.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timezone

from agenda.dates import TZ_SDQ
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

API = "https://api.tix.do/api/events"
EVENT_URL = "https://tix.do/event/{slug}"
MAX_PAGES = 5
MAX_DESCRIPTION = 280
FIELDS = ["name", "slug", "start_at", "end_at", "free", "place", "description"]

SKIP_CATEGORIES = {"deporte", "wellness", "crecimiento personal"}
CATEGORIES = {"música": "Música", "musica": "Música", "teatro": "Teatro", "comedia": "Teatro"}
# Ciudades fuera de Santo Domingo que aparecen en `place`.
ELSEWHERE = re.compile(
    r"\b(santiago|cibao|punta cana|b[aá]varo|cap cana|la romana|puerto plata|sos[uú]a|cabarete|jarabacoa|constanza|"
    r"saman[aá]|las terrenas|las galeras|moca|la vega|san crist[oó]bal|ban[ií]|higuey|hig[uü]ey|bayah[ií]be|juan dolio|"
    r"boca chica|nagua|salcedo|san francisco de macor[ií]s|san pedro de macor[ií]s|azua|barahona|monte cristi|"
    r"miami|new york|nueva york|madrid|panam[aá]|colombia|puerto rico|quito|neyba|guaymate|utesa|"
    r"centro le[oó]n|eduardo le[oó]n jim[eé]ne[sz])\b",
    re.I,
)
# Salas de Santo Domingo que no están en models.ZONES pero salen en TIX.
SDQ_PLACES = re.compile(
    r"\b(santo domingo|sdq|distrito nacional|velvet room|lucia sdq|galer[ií]a 360|escenario 360|pabell[oó]n de la fama|"
    r"the box working space|max\.? h[ea]r?r?[ií]quez|ure[ñn]a|colonial|blue mall|sambil|[aá]gora mall|"
    r"sala manuel rueda|bellas artes|jard[ií]n bot[aá]nico|lope de vega|19 de marzo|rep[uú]blica brewing|"
    r"villa palmera|fuerzas armadas)\b",
    re.I,
)
VIRTUAL = re.compile(r"^\s*(online|virtual|en l[ií]nea|zoom)\s*$", re.I)


def query_params(now_utc: datetime, page: int) -> list[tuple[str, str]]:
    params = [
        ("filters[status]", "active"),
        ("filters[end_at][$gte]", now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        ("sort[0]", "start_at"),
        ("pagination[pageSize]", "100"),
        ("pagination[page]", str(page)),
        ("populate[event_category][fields][0]", "name"),
    ]
    params += [(f"fields[{i}]", f) for i, f in enumerate(FIELDS)]
    return params


def _local(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(TZ_SDQ)
    except (TypeError, ValueError):
        return None


def _category_name(attrs: dict) -> str:
    cat = attrs.get("event_category") or {}
    data = cat.get("data") if isinstance(cat, dict) else None
    name = ((data or {}).get("attributes") or {}).get("name") or ""
    return re.sub(r"^[^\wÁÉÍÓÚÑáéíóúñ]+", "", name).strip()  # "🎵 Música" -> "Música"


def place_verdict(place: str) -> str:
    """'sdq', 'fuera' o 'desconocido' según el nombre de la sala."""
    p = place or ""
    if zone_for(p) or SDQ_PLACES.search(p):
        return "sdq"
    if ELSEWHERE.search(p):
        return "fuera"
    return "desconocido"


def _description(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "", text or "")  # ningún correo pasa al sitio
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_DESCRIPTION else text[: MAX_DESCRIPTION - 1].rstrip() + "…"


def parse_item(item: dict, today: date) -> Event | None:
    a = item.get("attributes") if isinstance(item, dict) and "attributes" in item else item
    if not isinstance(a, dict):
        return None
    title = re.sub(r"\s+", " ", a.get("name") or "").strip()
    slug = (a.get("slug") or "").strip()
    start, end = _local(a.get("start_at")), _local(a.get("end_at"))
    if not title or not slug or not start:
        return None
    if end and end < start:
        end = None
    last = (end or start).date()
    if last < today:
        return None
    category_name = _category_name(a)
    if category_name.lower() in SKIP_CATEGORIES:
        return None
    place = re.sub(r"\s+", " ", a.get("place") or "").strip()
    if place.lower().startswith("http"):
        place = ""  # algunos organizadores ponen un enlace de Google Maps en vez de la sala
    if VIRTUAL.match(place):
        return None  # la agenda es de eventos para ir en persona
    verdict = place_verdict(place)
    if verdict == "fuera":
        return None

    multi_day = end is not None and end.date() > start.date()
    first = max(start.date(), today) if multi_day else start.date()
    dates = [first.isoformat(), end.date().isoformat()] if multi_day else [start.date().isoformat()]
    desc = _description(a.get("description") or "")
    category = CATEGORIES.get(category_name.lower()) or normalize_category(title, category_name, desc)
    free = a.get("free")
    return Event(
        source="tix",
        source_name="TIX",
        url=EVENT_URL.format(slug=slug),
        title=title,
        dates=dates,
        start_time=None if multi_day else start.strftime("%H:%M"),  # en un rango, la hora es la de la venta
        venue=place,
        zone=zone_for(place),
        category=category,
        is_free=True if free is True else (False if free is False else None),
        price_min=0 if free is True else None,  # de pago: el monto no viene en esta API
        kids=guess_kids(title, desc, category_name),
        tags=["formacion"] if category_name.lower() == "workshop" else [],
        description=desc,
        ticket_url=EVENT_URL.format(slug=slug),
        needs_review=verdict == "desconocido",
    )


class Tix(Source):
    id = "tix"
    name = "TIX"
    delay = 3.0

    def run(self) -> list[Event]:
        now = datetime.now(timezone.utc)
        out, page, pages = [], 1, 1
        while page <= min(pages, MAX_PAGES):
            data = self.fetcher.get(API, delay=self.delay, params=query_params(now, page)).json()
            items = data.get("data") or []
            pages = int(((data.get("meta") or {}).get("pagination") or {}).get("pageCount") or 1)
            out += [ev for ev in (parse_item(it, self.today) for it in items) if ev]
            page += 1
        known = [e for e in out if not e.needs_review]
        unknown = Counter(e.venue or "(sin sala)" for e in out if e.needs_review)
        self.log(f"[{self.id}] {len(known)} eventos en salas de Santo Domingo; {sum(unknown.values())} en salas que no "
                 f"se reconocen y no se publican")
        if unknown:
            self.log(f"[{self.id}] salas por reconocer (agregar a SDQ_PLACES si son de Santo Domingo): "
                     + ", ".join(f"{v} ({n})" for v, n in unknown.most_common(15)))
        return known
