"""Deduplicación de eventos para la Agenda Cultural de Santo Domingo.

Cada adaptador produce Event. dedupe(events) devuelve una lista donde los
eventos que son la misma ocurrencia, vistos en varias fuentes, quedan
fusionados en uno solo con la mejor información de cada fuente.

Solo usa la biblioteca estándar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

# --------------------------------------------------------------------------
# Modelo mínimo. Si ya tienes tu propio Event, basta con que tenga estos campos.
# --------------------------------------------------------------------------


@dataclass
class Event:
    title: str
    start: datetime                      # fecha (y hora si has_time)
    source: str                          # id del adaptador, p. ej. "teatro_nacional"
    venue: Optional[str] = None
    has_time: bool = True                # False si la fuente solo trae la fecha
    url: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    is_free: Optional[bool] = None       # None = desconocido
    price_min: Optional[int] = None      # RD$
    price_max: Optional[int] = None
    sources: list = field(default_factory=list)    # [(source, url), ...] tras fusionar
    conflicts: list = field(default_factory=list)  # avisos para revisión manual


# Fuentes más confiables primero. Estructuradas (API / JSON-LD) por encima de
# HTML, y HTML por encima de blogs y agregadores.
SOURCE_PRIORITY = [
    "teatro_nacional",
    "casa_teatro",
    "zonacolonial",
    "cce",
    "jazz_dominicana",
]


def _rank(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------

STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "al", "y", "e", "en", "con", "a",
    "un", "una", "por", "para", "presenta", "presentan", "concierto", "noche",
    "the", "of", "and", "live", "en vivo", "vivo",
}

# Alias de sedes -> forma canónica. Agrega aquí cada variante que veas.
VENUE_ALIASES = {
    "teatro nacional eduardo brito": "teatro nacional",
    "teatro nacional": "teatro nacional",
    "palacio de bellas artes": "teatro nacional",
    "centro cultural de espana": "cce",
    "centro cultural de espana en santo domingo": "cce",
    "cce": "cce",
    "casa de teatro": "casa de teatro",
    "alianza francesa": "alianza francesa",
    "centro cultural banreservas": "banreservas",
}


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def norm_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_tokens(title: str) -> list:
    return [t for t in norm_text(title).split() if t not in STOPWORDS]


def norm_venue(venue: Optional[str]) -> str:
    v = norm_text(venue)
    if not v:
        return ""
    if v in VENUE_ALIASES:
        return VENUE_ALIASES[v]
    # Alias por prefijo/contención: "Teatro Nacional, Sala Carlos Piantini"
    for alias, canon in sorted(VENUE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if v.startswith(alias) or alias in v:
            return canon
    return v


# --------------------------------------------------------------------------
# Comparación
# --------------------------------------------------------------------------


def title_similarity(a: str, b: str) -> float:
    """0..1. Combina texto completo, tokens y contención."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    jaccard = len(sa & sb) / len(sa | sb)
    seq = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    # Contención: "Retro Jazz" dentro de "Retro Jazz: Noche de standards".
    # Exige al menos 2 tokens o 8 caracteres para no unir "Jazz" con todo.
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    containment = 0.0
    if small <= big and (len(small) >= 2 or sum(len(t) for t in small) >= 8):
        containment = 0.9
    return max(jaccard, seq, containment)


def venues_compatible(a: Optional[str], b: Optional[str]) -> tuple:
    """(compatible, confirmado). Si falta una sede es compatible pero no confirmado."""
    va, vb = norm_venue(a), norm_venue(b)
    if not va or not vb:
        return True, False
    if va == vb or va in vb or vb in va:
        return True, True
    return False, False


def times_compatible(a: Event, b: Event, tolerance_min: int = 90) -> tuple:
    """(compatible, confirmado). Mismo día obligatorio; hora solo si ambos la traen."""
    if a.start.date() != b.start.date():
        return False, False
    if not (a.has_time and b.has_time):
        return True, False
    diff = abs(a.start - b.start)
    return diff <= timedelta(minutes=tolerance_min), True


def is_same_event(a: Event, b: Event) -> bool:
    ok_t, time_confirmed = times_compatible(a, b)
    if not ok_t:
        return False
    ok_v, venue_confirmed = venues_compatible(a.venue, b.venue)
    if not ok_v:
        return False

    sim = title_similarity(a.title, b.title)
    if sim >= 0.85:
        return True
    # Título menos parecido: exige respaldo de sede Y hora confirmadas.
    if sim >= 0.6 and venue_confirmed and time_confirmed:
        return True
    return False


# --------------------------------------------------------------------------
# Agrupación (union-find) y fusión
# --------------------------------------------------------------------------


def _group(events: list) -> list:
    n = len(events)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Bloqueo por fecha: solo se comparan eventos del mismo día.
    by_day = {}
    for i, e in enumerate(events):
        by_day.setdefault(e.start.date(), []).append(i)

    for idxs in by_day.values():
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                i, j = idxs[x], idxs[y]
                # Dos eventos de la misma fuente son ocurrencias distintas.
                if events[i].source == events[j].source:
                    continue
                if is_same_event(events[i], events[j]):
                    parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(events[i])
    return list(groups.values())


def _first(values):
    for v in values:
        if v not in (None, "", []):
            return v
    return None


def merge_group(group: list) -> Event:
    if len(group) == 1:
        e = group[0]
        e.sources = e.sources or [(e.source, e.url)]
        return e

    g = sorted(group, key=lambda e: _rank(e.source))
    best = g[0]
    merged = Event(
        title=best.title,
        start=best.start,
        source=best.source,
        venue=_first(e.venue for e in g),
        has_time=best.has_time,
        url=_first(e.url for e in g),
        category=_first(e.category for e in g),
        # La descripción más larga suele ser la más útil.
        description=max((e.description or "" for e in g), key=len) or None,
    )

    # Hora: la de la fuente de mayor prioridad que la tenga.
    with_time = [e for e in g if e.has_time]
    if with_time:
        merged.start, merged.has_time = with_time[0].start, True
        times = {e.start.strftime("%H:%M") for e in with_time}
        if len(times) > 1:
            merged.conflicts.append(f"hora distinta entre fuentes: {sorted(times)}")

    # Precio: solo de fuentes que lo informan; prioridad por fuente.
    priced = [e for e in g if e.is_free is not None or e.price_min is not None]
    if priced:
        p = priced[0]
        merged.is_free, merged.price_min, merged.price_max = (
            p.is_free, p.price_min, p.price_max,
        )
        distinct = {(e.is_free, e.price_min, e.price_max) for e in priced}
        if len(distinct) > 1:
            merged.conflicts.append(
                "precio distinto entre fuentes: "
                + "; ".join(f"{e.source}={e.price_min}-{e.price_max} gratis={e.is_free}" for e in priced)
            )

    merged.sources = [(e.source, e.url) for e in g]
    return merged


def dedupe(events: list) -> list:
    merged = [merge_group(grp) for grp in _group(events)]
    return sorted(merged, key=lambda e: (e.start, norm_text(e.title)))
