"""Modelo común de evento + normalización de categorías y zonas."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

CATEGORY_RULES = [
    ("Danza", r"\b(danza|ballet|baile)"),
    ("Cine", r"\b(cine|audiovisual|pel[ií]cula|proyecci[oó]n|cortometraje|documental|filmoteca)"),
    # El teatro musical es teatro: va antes de Música, que si no se lo queda por "musical".
    ("Teatro", r"\b(teatro|comedia|obra)\s+musical"),
    (
        "Música",
        r"\b(m[uú]sica|musical|concierto|jazz|sinf[oó]n|recital|sonido|orquesta|banda|canto|coral|[oó]pera|l[ií]rica)",
    ),
    ("Teatro", r"\b(teatro|obra|esc[eé]nic|comedia|stand\s?up|mon[oó]logo)"),
    (
        "Arte",
        r"\b(artes?\b|exposici[oó]n|galer[ií]a|pintura|escultura|fotograf|visuales|performance"
        r"|video\s?mapping|instalaci[oó]n\s+(art[ií]stica|sonora|inmersiva)"
        r"|muestra\s+(colectiva|individual|de\s+(arte|pintura|fotograf|escultura))"
        r"|vernissage|curadur|murales?\b)",  # no confundir "mural" con "Muralla"
    ),
]
DEFAULT_CATEGORY = "Cultura"

_KIDS = re.compile(r"\b(ni[ñn]os?|ni[ñn]as?|infantil(?:es)?|familia(?:r|res|s)?|kids)\b", re.I)

# (fragmento en minúsculas, zona)
ZONES = [
    ("casa de teatro", "Ciudad Colonial"),
    ("las damas", "Ciudad Colonial"),
    ("zona colonial", "Ciudad Colonial"),
    ("ciudad colonial", "Ciudad Colonial"),
    ("ruinas de san francisco", "Ciudad Colonial"),
    ("parque pellerano castro", "Ciudad Colonial"),
    ("plaza de la cultura", "Plaza de la Cultura"),
    ("plaza de españa", "Ciudad Colonial"),
    ("centro cultural de españa", "Ciudad Colonial"),
    ("quinta dominica", "Ciudad Colonial"),
    ("casa del cordón", "Ciudad Colonial"),
    ("museo de la catedral", "Ciudad Colonial"),
    ("academia dominicana de la lengua", "Ciudad Colonial"),
    ("centro cultural banreservas", "Ciudad Colonial"),
    ("teatro nacional", "Plaza de la Cultura"),
    ("museo de arte moderno", "Plaza de la Cultura"),
    ("museo nacional de historia natural", "Plaza de la Cultura"),
    ("cinemateca", "Plaza de la Cultura"),
    ("the green room", "Piantini"),
    ("torre piantini", "Piantini"),
    ("dominican fiesta", "Mirador Sur"),
    ("plaza montesinos", "Malecón"),
]


def normalize_category(*texts: str) -> str:
    blob = " ".join(t for t in texts if t)
    for name, rx in CATEGORY_RULES:
        if re.search(rx, blob, re.I):
            return name
    return DEFAULT_CATEGORY


def guess_kids(*texts: str) -> bool:
    return bool(_KIDS.search(" ".join(t for t in texts if t)))


def zone_for(venue: str, default: str = "") -> str:
    v = (venue or "").lower()
    for frag, zone in ZONES:
        if frag in v:
            return zone
    return default


@dataclass
class Event:
    source: str
    source_name: str
    url: str
    title: str
    dates: list[str]  # ISO, ordenadas; 1 = evento de un día, varias = rango o sesiones
    start_time: str | None = None  # 'HH:MM'
    venue: str = ""
    zone: str = ""
    category: str = DEFAULT_CATEGORY
    is_free: bool | None = None  # None = precio sin confirmar
    price_min: int | None = None
    price_max: int | None = None
    kids: bool = False
    tags: list[str] = field(default_factory=list)
    description: str = ""
    ticket_url: str = ""
    needs_review: bool = False

    @property
    def start(self) -> str:
        return self.dates[0]

    @property
    def end(self) -> str:
        return self.dates[-1]

    @property
    def key(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.url}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    def content_hash(self) -> str:
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def to_public(self) -> dict:
        """Forma que consume el frontend (la misma del prototipo)."""
        if self.is_free:
            price = 0
        elif self.is_free is False:
            price = self.price_min
        else:
            price = None
        return {
            "id": self.key,
            "source": self.source,
            "date": self.start,
            "end": self.end if self.end != self.start else None,
            "sessions": self.dates if len(self.dates) > 2 else None,
            "title": self.title,
            "venue": self.venue,
            "zone": self.zone,
            "cat": self.category,
            "price": price,
            "price_max": self.price_max if self.is_free is False else None,
            "time": self.start_time or "",
            "kids": self.kids,
            "tags": self.tags,
            "description": self.description,
            "ticketUrl": self.ticket_url,
            "srcName": self.source_name,
            "srcUrl": self.url,
        }
