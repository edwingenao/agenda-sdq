"""Fechas, horas y precios tal como aparecen en textos en español dominicano.

Todo es texto -> valores Python, sin red ni estado, para poder probarlo offline.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

# República Dominicana: UTC-4 todo el año, sin cambio de horario.
TZ_SDQ = timezone(timedelta(hours=-4))


def today_sdq(now: datetime | None = None) -> date:
    """La fecha de hoy en Santo Domingo. Los servidores de GitHub corren en UTC: con date.today(), una corrida
    después de las 8:00 p. m. ya creería que es mañana y dejaría fuera los eventos de esa noche."""
    return (now or datetime.now(timezone.utc)).astimezone(TZ_SDQ).date()

MONTHS = {
    "ene": 1, "enero": 1,
    "feb": 2, "febrero": 2,
    "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6,
    "jul": 7, "julio": 7,
    "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "set": 9, "septiembre": 9, "setiembre": 9,
    "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_YEAR = r"(?:\s*,?\s*(?:de\s+)?(?P<y>\d{4}))?"

_RX = {
    # "del 30 de abril al 3 de mayo de 2026": el año, si está, va al final y vale para las dos fechas
    "cross": re.compile(
        rf"(?P<d1>\d{{1,2}})\s+de\s+(?P<m1>{_MON})\b\.?(?:\s*,?\s*(?:de\s+)?(?P<y1>\d{{4}}))?"
        rf"\s*(?:al|a|hasta\s+el|-|–|—)\s*(?P<d2>\d{{1,2}})\s+de\s+(?P<m2>{_MON})\b\.?{_YEAR}", re.I
    ),
    # "del 9 al 18 de octubre, 2026"
    "range": re.compile(
        rf"(?P<d1>\d{{1,2}})\s*(?:al|a|-|–|—)\s*(?P<d2>\d{{1,2}})\s+de\s+(?P<m>{_MON})\b\.?{_YEAR}", re.I
    ),
    # "7 y 8 de octubre"
    "list": re.compile(
        rf"(?P<d1>\d{{1,2}})\s*(?:y|,)\s*(?P<d2>\d{{1,2}})\s+de\s+(?P<m>{_MON})\b\.?{_YEAR}", re.I
    ),
    # "17/Oct/2026" (Centro Cultural de España)
    "slash": re.compile(rf"(?P<d>\d{{1,2}})\s*/\s*(?P<m>{_MON})\.?\s*/\s*(?P<y>\d{{4}})", re.I),
    # "17/10/2026"
    "num": re.compile(r"(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})"),
    # "7 de octubre, 2026" / "7 de octubre"
    "long": re.compile(rf"(?P<d>\d{{1,2}})\s+de\s+(?P<m>{_MON})\b\.?{_YEAR}", re.I),
    # "OCT 06" (zonacolonial.do)
    "md": re.compile(rf"\b(?P<m>{_MON})\.?\s+(?P<d>\d{{1,2}})\b{_YEAR}", re.I),
}


def _mk(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def infer_year(month: int, day: int, today: date) -> date | None:
    """Fecha sin año: la ocurrencia más cercana, tolerando hasta 120 días hacia atrás."""
    cand = _mk(today.year, month, day)
    if cand is None:
        return None
    if cand < today - timedelta(days=120):
        cand = _mk(today.year + 1, month, day)
    return cand


def month_day(month_name: str, day: int | str, today: date, year: int | str | None = None) -> date | None:
    mo = MONTHS.get(month_name.lower().strip("."))
    if mo is None:
        return None
    if year:
        return _mk(int(year), mo, int(day))
    return infer_year(mo, int(day), today)


def _cross(g: dict, today: date) -> list[date | None]:
    """Rango que cruza de mes. Sin año en la primera fecha, toma el de la segunda (o el anterior si cruza de año)."""
    m1, m2 = MONTHS.get(g["m1"].lower().strip(".")), MONTHS.get(g["m2"].lower().strip("."))
    if m1 is None or m2 is None:
        return []
    end = month_day(g["m2"], g["d2"], today, g.get("y"))
    if end is None:
        return []
    y1 = int(g["y1"]) if g.get("y1") else (end.year - 1 if m1 > m2 else end.year)
    start = _mk(y1, m1, int(g["d1"]))
    if start is None or start > end:
        return []
    return [start, end]


def find_dates(
    text: str,
    today: date,
    *,
    month_day_pattern: bool = False,
    only_slash: bool = False,
) -> list[date]:
    """Todas las fechas del texto, únicas y ordenadas. Los rangos devuelven sus dos extremos."""
    spans: list[tuple[int, int]] = []
    found: list[date] = []

    def free(span: tuple[int, int]) -> bool:
        return not any(span[0] < e and span[1] > s for s, e in spans)

    if only_slash:
        order = ["slash"]
    else:
        order = ["cross", "range", "list", "slash", "num", "long"] + (["md"] if month_day_pattern else [])

    for name in order:
        for m in _RX[name].finditer(text):
            if not free(m.span()):
                continue
            g = m.groupdict()
            if name == "cross":
                ds = _cross(g, today)
            elif name in ("range", "list"):
                a, b = int(g["d1"]), int(g["d2"])
                if a >= b:
                    continue
                ds = [month_day(g["m"], a, today, g.get("y")), month_day(g["m"], b, today, g.get("y"))]
            elif name == "num":
                ds = [_mk(int(g["y"]), int(g["m"]), int(g["d"]))]
            else:
                ds = [month_day(g["m"], g["d"], today, g.get("y"))]
            spans.append(m.span())
            found.extend(d for d in ds if d)
    return sorted(set(found))


# --- horas -----------------------------------------------------------------

_T12 = re.compile(r"(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>a\.?\s*m\.?|p\.?\s*m\.?)", re.I)
_T24 = re.compile(r"\b(?P<h>[01]?\d|2[0-3]):(?P<mi>[0-5]\d)\b(?!\s*[ap]\.?\s*m)", re.I)


def parse_time(text: str) -> str | None:
    """Primera hora del texto como 'HH:MM' (24 h). '8:30 p. m.' -> '20:30'."""
    best: tuple[int, str] | None = None
    for m in _T12.finditer(text):
        h = int(m.group("h"))
        mi = int(m.group("mi") or 0)
        ap = re.sub(r"[\s.]", "", m.group("ap").lower())
        if not 1 <= h <= 12:
            continue
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        cand = (m.start(), f"{h:02d}:{mi:02d}")
        if best is None or cand[0] < best[0]:
            best = cand
        break
    for m in _T24.finditer(text):
        cand = (m.start(), f"{int(m.group('h')):02d}:{m.group('mi')}")
        if best is None or cand[0] < best[0]:
            best = cand
        break
    return best[1] if best else None


# --- precios ---------------------------------------------------------------

_FREE = re.compile(
    r"\b(gratis|gratuit[oa]s?|entrada\s+libre|entrada\s+gratuita|acceso\s+libre|libre\s+acceso)\b", re.I
)
_AMOUNT = re.compile(
    r"(?:RD\s*\$|\$)\s*(?P<n>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)", re.I
)


def _to_int(s: str) -> int:
    s = s.strip()
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) >= 2 and len(parts[-1]) == 3:
            s = s.replace(sep, "")
        else:
            s = s.replace(sep, ".")
    return int(round(float(s)))


def parse_price(text: str) -> tuple[bool | None, int | None, int | None]:
    """(es_gratis, precio_min, precio_max) en RD$. (None, None, None) si el texto no dice nada."""
    amounts = [_to_int(m.group("n")) for m in _AMOUNT.finditer(text)]
    free = bool(_FREE.search(text))
    positive = [a for a in amounts if a > 0]
    if positive:
        return False, min(positive), max(positive)
    if free or amounts:
        return True, 0, 0
    return None, None, None
