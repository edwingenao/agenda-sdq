"""SIC-RD, agenda cultural del Ministerio de Cultura (sic.cultura.gob.do/agenda-cultural): API JSON pública.

Verificado el 6 oct 2026. La página es una app de JavaScript que consulta
    GET https://apisic.cultura.gob.do/api/public/v1/events?date_from=AAAA-MM-DD&page=N
sin autenticación. robots.txt del API: `Disallow:` vacío (todo permitido).
Paginación estilo Laravel: data, current_page, last_page, total; 12 por página aunque se pida más.
`date_from` filtra eventos desde esa fecha inclusive (con 2026-09-29 devolvió 7 de 20).
Campos: id, name, date (medianoche UTC: es solo la fecha), time ("10:00:00"), place (texto libre),
modality (presencial|virtual|...), access_type (abierto|invitacion_cerrada), cost ("0.00"), url (casi siempre null),
type.name (Concierto, Conferencia, Conversatorio, Taller, Foro...), municipality.nombre y municipality.province.nombre.
No trae descripción, ni siquiera en /events/{id}. cover_photo_url es una URL firmada que vence en 1 hora: no se guarda.
Página pública de cada evento: https://sic.cultura.gob.do/agenda/evento/{id}.
Ese día los 20 eventos eran gratis y ninguno era futuro; había un repetido (ids 27 y 29) que aquí se une.
"""

from __future__ import annotations

import json

from agenda.dedupe import is_same_event
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

API = "https://apisic.cultura.gob.do/api/public/v1/events"
PUBLIC = "https://sic.cultura.gob.do/agenda/evento/{id}"
MAX_PAGES = 10

# Provincias y municipios que cuentan como Santo Domingo.
SDQ = {"distrito nacional", "d.n", "d.n.", "santo domingo", "santo domingo este", "santo domingo oeste",
       "santo domingo norte"}
# Tipos de charla o formación: su título suele nombrar la sede ("... en el Teatro Nacional"), así que la
# categoría por palabras clave fallaría; van siempre a Cultura.
TIPOS_CULTURA = {"conferencia", "conversatorio", "foro", "taller", "lanzamiento de libro",
                 "lanzamiento de premio", "feria del libro"}


def _in_sdq(it: dict) -> bool | None:
    """True/False según el municipio; None si la API no lo trae."""
    m = it.get("municipality")
    if not m:
        return None
    names = {(m.get("nombre") or "").strip().lower(), ((m.get("province") or {}).get("nombre") or "").strip().lower()}
    return bool(names & SDQ)


def _money(v) -> int | None:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def parse_events(payload: str | dict, today) -> list[Event]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    items = data.get("data", []) if isinstance(data, dict) else data
    out: list[Event] = []
    for it in sorted(items, key=lambda x: x.get("id") or 0):
        title = (it.get("name") or "").strip()
        day = (it.get("date") or "")[:10]
        if not title or len(day) != 10 or day < today.isoformat():
            continue
        if (it.get("access_type") or "abierto") != "abierto" or (it.get("modality") or "presencial") == "virtual":
            continue
        tipo = ((it.get("type") or {}).get("name") or "").strip()
        if tipo.lower() == "webbinar":
            continue
        where = _in_sdq(it)
        if where is False:
            continue
        place = " ".join((it.get("place") or "").split())

        cost = _money(it.get("cost"))
        is_free = None if cost is None else cost == 0
        if tipo.lower() == "concierto":
            category = "Música"
        elif tipo.lower() in TIPOS_CULTURA:
            category = "Cultura"
        else:
            category = normalize_category(title, tipo)

        ev = Event(
            source="sic",
            source_name="Ministerio de Cultura (SIC)",
            url=PUBLIC.format(id=it["id"]),
            title=title,
            dates=[day],
            start_time=(it.get("time") or "")[:5] or None,
            venue=place,
            zone=zone_for(place),
            category=category,
            is_free=is_free,
            price_min=cost,
            kids=guess_kids(title),
            tags=["formacion"] if tipo.lower() == "taller" else [],
            description=tipo,
            ticket_url=it.get("url") or "",
            # Sin municipio no sabemos si es en Santo Domingo: se publica, pero para revisar.
            needs_review=where is None,
        )
        # La API trae repetidos (mismo evento cargado dos veces); se queda el primero cargado.
        if any(is_same_event(prev, ev) for prev in out):
            continue
        out.append(ev)
    return out


class MinisterioCulturaSIC(Source):
    id = "sic"
    name = "Ministerio de Cultura (SIC)"
    delay = 3.0

    def run(self) -> list[Event]:
        items: list[dict] = []
        page, last = 1, 1
        while page <= min(last, MAX_PAGES):
            r = self.fetcher.get(API, delay=self.delay, params={"date_from": self.today.isoformat(), "page": page})
            data = r.json()
            items += data.get("data", [])
            last = int(data.get("last_page") or 1)
            page += 1
        events = parse_events({"data": items}, self.today)
        if not events:
            self.log(f"[{self.id}] 0 eventos próximos (la API respondió pero no hay eventos futuros; puede ser normal).")
        return events
