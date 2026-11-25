"""Lugares (venues) de la agenda: carga `agenda/venues.json` y ubica el texto `venue` de un evento.

Las fuentes escriben el mismo lugar de muchas formas ("Teatro Nacional", "Sala Carlos Piantini, Teatro Nacional",
"Casa de Teatro. Olga Cerpa & Mestisay..."). Cada lugar del archivo lleva sus `aliases`; `Venues.find` compara sin
acentos ni mayúsculas, por palabras completas, y gana el alias más largo ("Museo de Arte Moderno" le gana a
"Plaza de la Cultura" en "Auditorio del Museo de Arte Moderno, Plaza de la Cultura").

Reglas:
  * Una coordenada solo entra con una fuente que se pueda citar (`coord_source`). Sin fuente, lat y lng van null:
    el lugar existe pero todavía no se puede poner en el mapa.
  * `precision` dice qué tan fina es la coordenada; el sitio debe mostrar "zona aproximada" cuando es `sector`.
  * El archivo se valida al cargar: un error de datos (alias repetido, coordenada fuera de Santo Domingo) lanza
    ValueError y la prueba falla, en vez de publicar un marcador en el mar.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from agenda.dedupe import norm_text

DEFAULT_PATH = Path(__file__).with_name("venues.json")
PRECISIONS = ("edificio", "calle", "sector")
# Santo Domingo y alrededores, con margen: atrapa signos o dígitos cambiados (lat_min, lat_max, lng_min, lng_max).
BBOX = (18.35, 18.60, -70.05, -69.75)
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Venue:
    id: str
    name: str
    aliases: tuple
    address: Optional[str] = None
    zone: str = ""
    city: str = "Santo Domingo"
    lat: Optional[float] = None
    lng: Optional[float] = None
    precision: Optional[str] = None
    coord_source: Optional[str] = None
    verified: bool = False
    notes: Optional[str] = None

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None

    def to_public(self) -> dict:
        """Lo que consume el mapa del sitio. Sin notas ni fuentes internas."""
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "zone": self.zone,
            "lat": self.lat,
            "lng": self.lng,
            "precision": self.precision,
        }


def _parse(raw: dict) -> Venue:
    if not isinstance(raw, dict):
        raise ValueError("la entrada no es un objeto")
    vid = raw.get("id")
    if not isinstance(vid, str) or not _SLUG.match(vid):
        raise ValueError(f"id inválido {vid!r} (usa minúsculas, números y guiones)")
    try:
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("sin nombre")
        aliases = raw.get("aliases")
        if not isinstance(aliases, list) or not aliases or not all(isinstance(a, str) and norm_text(a) for a in aliases):
            raise ValueError("aliases debe ser una lista de textos no vacíos")
        if any(len(norm_text(a)) < 3 for a in aliases):
            raise ValueError("un alias de menos de 3 letras daría falsos positivos")
        lat, lng = raw.get("lat"), raw.get("lng")
        for label, val in (("lat", lat), ("lng", lng)):
            if val is not None and (isinstance(val, bool) or not isinstance(val, (int, float))):
                raise ValueError(f"{label} debe ser un número o null")
        if (lat is None) != (lng is None):
            raise ValueError("lat y lng van juntas o ninguna")
        precision = raw.get("precision")
        if lat is not None:
            if not (BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lng <= BBOX[3]):
                raise ValueError(f"coordenada fuera de Santo Domingo: {lat}, {lng}")
            if precision not in PRECISIONS:
                raise ValueError(f"precision debe ser una de {PRECISIONS}")
            if not (raw.get("coord_source") or "").strip():
                raise ValueError("una coordenada sin coord_source no entra: cita de dónde salió")
        elif precision is not None:
            raise ValueError("precision sin coordenadas")
        verified = raw.get("verified", False)
        if not isinstance(verified, bool):
            raise ValueError("verified debe ser true o false")
        if verified and lat is None:
            raise ValueError("verified sin coordenadas")
    except ValueError as exc:
        raise ValueError(f"{vid}: {exc}") from None
    return Venue(
        id=vid,
        name=name.strip(),
        aliases=tuple(a.strip() for a in aliases),
        address=(raw.get("address") or "").strip() or None,
        zone=(raw.get("zone") or "").strip(),
        city=(raw.get("city") or "Santo Domingo").strip(),
        lat=float(lat) if lat is not None else None,
        lng=float(lng) if lng is not None else None,
        precision=precision,
        coord_source=(raw.get("coord_source") or "").strip() or None,
        verified=verified,
        notes=(raw.get("notes") or "").strip() or None,
    )


class Venues:
    def __init__(self, venues: Iterable[Venue]):
        self.venues = list(venues)
        self.by_id: dict[str, Venue] = {}
        self._index: list[tuple[str, Venue]] = []
        seen_alias: dict[str, str] = {}
        for v in self.venues:
            if v.id in self.by_id:
                raise ValueError(f"id repetido: {v.id}")
            self.by_id[v.id] = v
            for alias in v.aliases:
                key = norm_text(alias)
                if key in seen_alias and seen_alias[key] != v.id:
                    raise ValueError(f"alias repetido {alias!r}: {seen_alias[key]} y {v.id}")
                seen_alias[key] = v.id
                self._index.append((key, v))
        # El alias más largo gana; a igual largo, el orden del archivo.
        self._index.sort(key=lambda kv: -len(kv[0]))

    def find(self, text: Optional[str]) -> Optional[Venue]:
        """El lugar al que se refiere el texto `venue` de un evento, o None si no está registrado."""
        norm = norm_text(text)
        if not norm:
            return None
        padded = f" {norm} "
        for key, venue in self._index:
            if f" {key} " in padded:
                return venue
        return None


def load(path: str | Path = DEFAULT_PATH) -> Venues:
    """Lee y valida el archivo. Lanza ValueError si está mal armado."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("venues") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("el archivo debe ser un objeto con la lista 'venues'")
    return Venues(_parse(e) for e in entries)


_default: Optional[Venues] = None


def default() -> Venues:
    global _default
    if _default is None:
        _default = load()
    return _default
