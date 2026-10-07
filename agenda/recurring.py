"""Series recurrentes de la agenda cultural (Domingos de Bonyé y similares).

Muchos eventos de Santo Domingo no se publican como evento con fecha en ninguna
fuente que leemos: se repiten cada semana (Domingos de Bonyé) o por temporada
(ciclos de cine, Turizoneando). Aquí se describen una sola vez en un archivo
curado a mano, ``series_recurrentes.json``, y este módulo los convierte en
eventos con fecha para las próximas semanas.

Reglas de producto que respeta:
  * Precio: si la serie no dice que es gratis o de pago, ``is_free`` es ``None``
    ("precio no confirmado"). Nunca se asume gratis.
  * Hora: si la serie no trae hora, no se inventa (``has_time = False``).
  * Una serie sin reconfirmar hace tiempo se sigue mostrando, pero con
    ``needs_confirmation = True`` para que la web diga "confirma antes de ir".
  * Las series de temporada (ciclos, programas de verano) quedan con
    ``"active": false`` hasta que se anuncien las fechas de la próxima edición.
  * Toda serie lleva al menos una fuente: sin evidencia no entra.
  * Hasta 2 categorías, de Música, Gastronomía y Cultura.

Una entrada mal escrita no detiene la corrida: se salta y queda en
``RecurringResult.skipped_invalid`` para que el pipeline la registre. Un archivo
ilegible o con estructura equivocada sí lanza ``ValueError``.

Este módulo usa un ``Event`` provisional con los mismos campos que ``sic_rd.py`` y
``dedupe.py``; hay que reemplazarlo por el modelo real de ``agenda-sdq``.

Uso rápido:  python -m agenda.recurring [días]   (por defecto 28)
"""

from __future__ import annotations

import calendar
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Union

SOURCE_ID = "recurring"
DEFAULT_PATH = Path(__file__).with_name("series_recurrentes.json")
DEFAULT_HORIZON_DAYS = 28
DEFAULT_STALE_AFTER_DAYS = 60

CATEGORIES = ("Música", "Gastronomía", "Cultura")
MAX_CATEGORIES = 2
CONFIDENCE_LEVELS = ("oficial", "listado", "sin_verificar")
PRICE_STATUSES = ("free", "paid", "unconfirmed")
FREQUENCIES = ("weekly", "monthly_nth", "dates")
VALID_NTH = (1, 2, 3, 4, -1)
WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}


@dataclass
class Event:
    """Modelo provisional; campos alineados con sic_rd.py y dedupe.py."""

    title: str
    start: datetime
    source: str
    venue: Optional[str] = None
    has_time: bool = False
    url: Optional[str] = None
    category: list[str] = field(default_factory=list)
    description: Optional[str] = None
    is_free: Optional[bool] = None  # None = precio no confirmado
    price_min: Optional[Decimal] = None
    price_max: Optional[Decimal] = None
    sources: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    # Extras propios de las series
    source_event_id: Optional[str] = None
    series_id: Optional[str] = None
    end: Optional[datetime] = None
    confidence: str = "sin_verificar"
    needs_confirmation: bool = False
    last_confirmed: Optional[date] = None


@dataclass
class Series:
    id: str
    title: str
    active: bool
    freq: str
    sources: tuple
    weekdays: tuple = ()
    nth: Optional[int] = None
    dates: tuple = ()
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    exceptions: frozenset = frozenset()
    venue: Optional[str] = None
    categories: tuple = ()
    price_status: str = "unconfirmed"
    price_min: Optional[Decimal] = None
    price_max: Optional[Decimal] = None
    description: Optional[str] = None
    url: Optional[str] = None
    confidence: str = "sin_verificar"
    last_confirmed: Optional[date] = None
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
    notes: Optional[str] = None


@dataclass
class RecurringResult:
    events: list[Event] = field(default_factory=list)
    loaded: int = 0
    skipped_inactive: list[str] = field(default_factory=list)
    skipped_invalid: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)  # activas sin reconfirmar a tiempo
    empty: list[str] = field(default_factory=list)  # activas sin fechas en la ventana


# ---------------------------------------------------------------- helpers ---

def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _date(value, label: str) -> Optional[date]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}: fecha inválida {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}: fecha inválida {value!r}") from None


def _time(value, label: str) -> Optional[time]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) != 5:
        raise ValueError(f"{label}: hora inválida {value!r} (usa HH:MM)")
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}: hora inválida {value!r} (usa HH:MM)") from None


def _money(value, label: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label}: monto inválido {value!r}") from None
    if amount < 0:
        raise ValueError(f"{label}: monto negativo {value!r}")
    return amount


def _weekdays(value) -> tuple:
    items = value if isinstance(value, list) else [value]
    days = set()
    for item in items:
        key = _norm(item)
        if key not in WEEKDAYS:
            raise ValueError(f"weekday: día inválido {item!r}")
        days.add(WEEKDAYS[key])
    if not days:
        raise ValueError("weekday: falta el día")
    return tuple(sorted(days))


# ------------------------------------------------------------------ series ---

def parse_series(raw: dict) -> Series:
    """Convierte una entrada del archivo. Lanza ValueError si es inutilizable."""
    if not isinstance(raw, dict):
        raise ValueError("la entrada no es un objeto")
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError("sin id")
    sid = sid.strip()
    try:
        return _build(sid, raw)
    except ValueError as exc:
        raise ValueError(f"{sid}: {exc}") from None


def _build(sid: str, raw: dict) -> Series:
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("sin título")

    active = raw.get("active", True)
    if not isinstance(active, bool):
        raise ValueError("active debe ser true o false")

    pattern = raw.get("pattern")
    if not isinstance(pattern, dict):
        raise ValueError("falta pattern")
    freq = pattern.get("freq")
    if freq not in FREQUENCIES:
        raise ValueError(f"freq inválida {freq!r}")
    weekdays: tuple = ()
    nth = None
    dates: tuple = ()
    if freq in ("weekly", "monthly_nth"):
        weekdays = _weekdays(pattern.get("weekday"))
        if freq == "monthly_nth":
            nth = pattern.get("nth")
            if isinstance(nth, bool) or nth not in VALID_NTH:
                raise ValueError(f"nth inválido {nth!r} (usa 1, 2, 3, 4 o -1)")
            if len(weekdays) != 1:
                raise ValueError("monthly_nth admite un solo día de la semana")
    else:
        raw_dates = pattern.get("dates")
        if not isinstance(raw_dates, list) or not raw_dates:
            raise ValueError("dates está vacío")
        parsed = []
        for item in raw_dates:
            day = _date(item, "dates")
            if day is None:
                raise ValueError("dates tiene un valor vacío")
            parsed.append(day)
        dates = tuple(sorted(set(parsed)))

    start_time = _time(raw.get("start_time"), "start_time")
    end_time = _time(raw.get("end_time"), "end_time")
    if end_time is not None and start_time is None:
        raise ValueError("end_time sin start_time")

    valid_from = _date(raw.get("valid_from"), "valid_from")
    valid_until = _date(raw.get("valid_until"), "valid_until")
    if valid_from and valid_until and valid_from > valid_until:
        raise ValueError("valid_from es posterior a valid_until")

    exceptions = raw.get("exceptions") or []
    if not isinstance(exceptions, list):
        raise ValueError("exceptions debe ser una lista de fechas")
    exceptions = frozenset(_date(d, "exceptions") for d in exceptions)

    categories = raw.get("category")
    if not isinstance(categories, list) or not 1 <= len(categories) <= MAX_CATEGORIES:
        raise ValueError(f"category debe tener de 1 a {MAX_CATEGORIES} categorías")
    for cat in categories:
        if cat not in CATEGORIES:
            raise ValueError(f"categoría desconocida {cat!r}")

    price = raw.get("price") or {}
    if not isinstance(price, dict):
        raise ValueError("price debe ser un objeto")
    status = price.get("status", "unconfirmed")
    if status not in PRICE_STATUSES:
        raise ValueError(f"price.status inválido {status!r}")
    pmin = pmax = None
    if status == "free":
        pmin = pmax = Decimal("0")
    elif status == "paid":
        pmin = _money(price.get("min"), "price.min")
        pmax = _money(price.get("max"), "price.max")
        if pmin is not None and pmax is None:
            pmax = pmin
        if pmin is not None and pmax is not None and pmax < pmin:
            raise ValueError("price.max es menor que price.min")

    confidence = raw.get("confidence", "sin_verificar")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence inválida {confidence!r}")

    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources or not all(isinstance(s, dict) for s in sources):
        raise ValueError("sin fuentes: toda serie necesita al menos una")

    stale_after = raw.get("stale_after_days", DEFAULT_STALE_AFTER_DAYS)
    if isinstance(stale_after, bool) or not isinstance(stale_after, int) or stale_after < 1:
        raise ValueError("stale_after_days debe ser un entero positivo")

    url = raw.get("url") or next((s.get("url") for s in sources if s.get("url")), None)

    return Series(
        id=sid,
        title=title.strip(),
        active=active,
        freq=freq,
        sources=tuple(sources),
        weekdays=weekdays,
        nth=nth,
        dates=dates,
        start_time=start_time,
        end_time=end_time,
        valid_from=valid_from,
        valid_until=valid_until,
        exceptions=exceptions,
        venue=(raw.get("venue") or "").strip() or None,
        categories=tuple(categories),
        price_status=status,
        price_min=pmin,
        price_max=pmax,
        description=(raw.get("description") or "").strip() or None,
        url=url,
        confidence=confidence,
        last_confirmed=_date(raw.get("last_confirmed"), "last_confirmed"),
        stale_after_days=stale_after,
        notes=raw.get("notes"),
    )


# ------------------------------------------------------------- expansión ---

def _is_nth(day: date, nth: int) -> bool:
    if nth > 0:
        return (day.day - 1) // 7 + 1 == nth
    return day.day + 7 > calendar.monthrange(day.year, day.month)[1]  # nth == -1


def occurrences(series: Series, start: date, end: date) -> list[date]:
    """Fechas de la serie entre start y end, ambas incluidas."""
    lo = max(start, series.valid_from) if series.valid_from else start
    hi = min(end, series.valid_until) if series.valid_until else end
    if lo > hi:
        return []
    if series.freq == "dates":
        days = [d for d in series.dates if lo <= d <= hi]
    else:
        days = []
        day = lo
        while day <= hi:
            if day.weekday() in series.weekdays and (
                series.freq == "weekly" or _is_nth(day, series.nth)
            ):
                days.append(day)
            day += timedelta(days=1)
    return sorted(d for d in days if d not in series.exceptions)


def is_stale(series: Series, today: date) -> bool:
    if series.last_confirmed is None:
        return True
    return (today - series.last_confirmed).days > series.stale_after_days


def to_events(series: Series, days: list[date], today: date) -> list[Event]:
    needs = is_stale(series, today) or series.confidence == "sin_verificar"
    is_free = {"free": True, "paid": False}.get(series.price_status)
    out = []
    for day in days:
        start = datetime.combine(day, series.start_time or time(0, 0))
        end = None
        if series.end_time is not None:
            end = datetime.combine(day, series.end_time)
            if end <= start:  # termina pasada la medianoche
                end += timedelta(days=1)
        out.append(Event(
            title=series.title,
            start=start,
            source=SOURCE_ID,
            venue=series.venue,
            has_time=series.start_time is not None,
            url=series.url,
            category=list(series.categories),
            description=series.description,
            is_free=is_free,
            price_min=series.price_min,
            price_max=series.price_max,
            sources=[f"{SOURCE_ID}:{series.id}"],
            source_event_id=f"{series.id}:{day.isoformat()}",
            series_id=series.id,
            end=end,
            confidence=series.confidence,
            needs_confirmation=needs,
            last_confirmed=series.last_confirmed,
        ))
    return out


# ---------------------------------------------------------------- entrada ---

def _raw_entries(source: Union[str, Path, dict]) -> list:
    if isinstance(source, (str, Path)):
        with open(source, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = source
    entries = data.get("series") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("el archivo debe ser un objeto con la lista 'series'")
    return entries


def collect(
    source: Union[str, Path, dict] = DEFAULT_PATH,
    today: Optional[date] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    include_inactive: bool = False,
) -> RecurringResult:
    result = RecurringResult()
    today = today or date.today()
    window_end = today + timedelta(days=horizon_days)
    seen: set[str] = set()

    for index, raw in enumerate(_raw_entries(source), start=1):
        try:
            series = parse_series(raw)
            if series.id in seen:
                raise ValueError(f"{series.id}: id repetido")
        except ValueError as exc:
            result.skipped_invalid.append(f"entrada {index}: {exc}")
            continue
        seen.add(series.id)
        result.loaded += 1

        if not series.active and not include_inactive:
            result.skipped_inactive.append(series.id)
            continue
        days = occurrences(series, today, window_end)
        if not days:
            result.empty.append(series.id)
            continue
        if is_stale(series, today):
            result.stale.append(series.id)
        result.events.extend(to_events(series, days, today))

    result.events.sort(key=lambda e: (e.start, e.source_event_id or ""))
    return result


def events(**kwargs) -> list[Event]:
    return collect(**kwargs).events


if __name__ == "__main__":
    import sys

    horizon = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HORIZON_DAYS
    res = collect(horizon_days=horizon)
    for ev in res.events:
        when = ev.start.strftime("%a %d %b %Y" + (" %H:%M" if ev.has_time else ""))
        price = {True: "gratis", False: "de pago", None: "precio no confirmado"}[ev.is_free]
        flag = "  [confirmar antes de ir]" if ev.needs_confirmation else ""
        print(f"{when}  {ev.title}  ({ev.venue}; {price}){flag}")
    print(f"\n{len(res.events)} eventos en {horizon} días; {res.loaded} series cargadas")
    for label, ids in (
        ("inactivas", res.skipped_inactive),
        ("sin fechas en la ventana (¿terminó la temporada?)", res.empty),
        ("sin reconfirmar a tiempo", res.stale),
        ("INVÁLIDAS (corregir el archivo)", res.skipped_invalid),
    ):
        if ids:
            print(f"- {label}: {', '.join(ids)}")
