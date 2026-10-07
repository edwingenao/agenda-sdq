"""Centro León (centroleon.org.do): API REST pública de The Events Calendar (WordPress).

Verificado el 6 oct 2026:
    GET https://centroleon.org.do/wp-json/tribe/events/v1/events?per_page=50&start_date=AAAA-MM-DD
robots.txt solo cierra /wp-content/uploads/wpforms/. Pagina con `next_rest_url` (URL completa) y total_pages.
- `start_date` / `end_date` ya vienen en hora local de Santo Domingo: no se convierten (utc_* se ignora).
- `cost` vino vacío en los 19 eventos: precio por confirmar, nunca gratis.
- Los 19 eventos de ese día eran en Santiago (Av. 27 de Febrero 146). La agenda es de Santo Domingo, así que solo
  pasan los que tienen ciudad Santo Domingo / Distrito Nacional o la dirección de la extensión en la Ciudad Colonial
  (Calle Las Damas 42). Los demás se cuentan y se informan, para notar si el filtro deja todo fuera.
- Un evento sin sede no se publica: no se sabe dónde es.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

API = "https://centroleon.org.do/wp-json/tribe/events/v1/events"
PER_PAGE = 50
MAX_PAGES = 10
MAX_DESCRIPTION = 280

SD_PLACES = ("santo domingo", "distrito nacional", "santo domingo de guzman")
SD_ADDRESS_HINTS = ("las damas",)
FREE_WORDS = ("gratis", "gratuito", "gratuita", "libre", "free")


@dataclass
class LeonResult:
    events: list[Event] = field(default_factory=list)
    fetched: int = 0
    skipped_other_place: int = 0
    skipped_invalid: list[str] = field(default_factory=list)
    pages: int = 0


def _norm(text) -> str:
    text = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").strip()


def _dt(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _text(value) -> str:
    """HTML a texto plano, con espacios colapsados."""
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<(script|style)\b.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _venue(raw) -> tuple[str, str, str]:
    """(nombre para mostrar, ciudad, dirección). `venue` puede venir como lista vacía."""
    if not isinstance(raw, dict):
        return "", "", ""
    name = _text(raw.get("venue"))
    city = _text(raw.get("city"))
    address = _text(raw.get("address")).rstrip(", ")
    shown = name
    if name and city and _norm(city) not in _norm(name):
        shown = f"{name}, {city}"
    return shown, city, address


def is_santo_domingo(city: str, address: str = "") -> bool:
    if _norm(city) in SD_PLACES:
        return True
    return any(h in _norm(address) for h in SD_ADDRESS_HINTS)


def parse_price(cost) -> tuple[bool | None, int | None, int | None]:
    """Vacío o ilegible -> (None, None, None): precio por confirmar, jamás gratis."""
    text = _text(cost)
    if not text:
        return None, None, None
    amounts = []
    for m in re.findall(r"\d[\d.,]*", text):
        try:
            amounts.append(int(round(float(m.replace(",", "")))))
        except ValueError:
            pass
    if any(a > 0 for a in amounts):
        return False, min(amounts), max(amounts)
    if any(w in _norm(text) for w in FREE_WORDS) or (amounts and all(a == 0 for a in amounts)):
        return True, 0, None
    return None, None, None


def to_event(raw: dict) -> Event | None:
    """None si está oculto o sin publicar; ValueError si está roto."""
    if not isinstance(raw, dict):
        raise ValueError("el evento no es un objeto")
    if raw.get("hide_from_listings") or raw.get("status") not in (None, "publish"):
        return None
    title = _text(raw.get("title"))
    if not title:
        raise ValueError("sin título")
    start = _dt(raw.get("start_date"))
    if start is None:
        raise ValueError("start_date ilegible")
    end = _dt(raw.get("end_date"))
    all_day = bool(raw.get("all_day"))
    if end is not None and end < start:
        end = None
    dates = [start.date().isoformat()]
    if end is not None and end.date() > start.date():
        dates.append(end.date().isoformat())  # rango: la app lo muestra una vez con "Hasta"

    venue, _, address = _venue(raw.get("venue"))
    is_free, pmin, pmax = parse_price(raw.get("cost"))
    cats = [_text(c.get("name")) for c in raw.get("categories") or [] if isinstance(c, dict)]
    cats = [c for c in cats if c and c != "Programa de actividades"]
    desc = _text(raw.get("description")) or _text(raw.get("excerpt"))
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[: MAX_DESCRIPTION - 1].rstrip() + "…"
    blob = " ".join([title] + cats)
    return Event(
        source="centro_leon",
        source_name="Centro León",
        url=raw.get("url") or f"https://centroleon.org.do/?p={raw.get('id')}",
        title=title,
        dates=dates,
        start_time=None if all_day else start.strftime("%H:%M"),  # nunca se inventa hora
        venue=venue,
        zone=zone_for(f"{venue} {address}"),
        category=normalize_category(*cats, title),
        is_free=is_free,
        price_min=pmin,
        price_max=pmax if pmax and pmax != pmin else None,
        kids=guess_kids(blob),
        tags=["formacion"] if re.search(r"taller|educaci[oó]n", blob, re.I) else [],
        description=desc,
    )


def collect(get_json, today, max_pages: int = MAX_PAGES) -> LeonResult:
    """Lee las páginas de la API y devuelve los eventos de Santo Domingo.

    Si falla la primera página, el error sube (la fuente queda como ERROR en la corrida); si falla una
    página siguiente, se conserva lo ya leído y se informa.
    """
    res = LeonResult()
    seen: set = set()
    url = f"{API}?per_page={PER_PAGE}&start_date={today.isoformat()}"
    while url and res.pages < max_pages:
        try:
            payload = get_json(url)
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise ValueError("respuesta sin lista 'events'")
        except Exception as exc:  # noqa: BLE001
            if res.pages == 0:
                raise
            res.skipped_invalid.append(f"página {res.pages + 1}: {exc}")
            break
        res.pages += 1
        for i, raw in enumerate(payload["events"]):
            res.fetched += 1
            ident = raw.get("id") if isinstance(raw, dict) else f"#{i}"
            try:
                if not isinstance(raw, dict):
                    raise ValueError("el evento no es un objeto")
                _, city, address = _venue(raw.get("venue"))
                if not is_santo_domingo(city, address):
                    res.skipped_other_place += 1
                    continue
                ev = to_event(raw)
            except ValueError as exc:
                res.skipped_invalid.append(f"evento {ident}: {exc}")
                continue
            if ev is None or ident in seen:
                continue
            seen.add(ident)
            res.events.append(ev)
        url = payload.get("next_rest_url") or None
    res.events.sort(key=lambda e: (e.start, e.start_time or "", e.url))
    return res


class CentroLeon(Source):
    id = "centro_leon"
    name = "Centro León"
    delay = 3.0

    def run(self) -> list[Event]:
        res = collect(lambda url: self.fetcher.get(url, delay=self.delay).json(), self.today)
        self.log(f"[{self.id}] {res.fetched} eventos leídos, {res.skipped_other_place} fuera de Santo Domingo "
                 f"(se omiten), {len(res.events)} en Santo Domingo")
        for s in res.skipped_invalid:
            self.log(f"[{self.id}] omitido: {s}")
        return res.events
