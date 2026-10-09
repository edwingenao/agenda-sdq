"""Ubica en OpenStreetMap (Nominatim) los lugares de agenda/venues.json que no tienen coordenadas.

Uso (desde la PC, con AGENDA_CONTACT definido):
    python -m agenda.geocode                  # solo informa: escribe data/venues_geocodificacion.md
    python -m agenda.geocode --aplicar        # además guarda en venues.json las coordenadas que pasan los filtros
    python -m agenda.geocode --revisar        # compara también las coordenadas que ya existen (nunca las cambia)
    python -m agenda.geocode --solo casa-de-teatro --solo sambil

Reglas:
  * Usa el `Fetcher` del proyecto: se identifica, respeta robots.txt y espera entre peticiones (Nominatim pide
    como máximo 1 por segundo). Si robots.txt no permite la consulta, se detiene: no se esquiva. El informe trae
    siempre un enlace para buscar cada lugar a mano en openstreetmap.org.
  * Nunca guarda a ciegas. Un resultado solo se aplica si cae dentro de Santo Domingo y el nombre del resultado se
    parece al del lugar; si no, queda en el informe para que lo revises. Lo aplicado entra con verified false.
  * No sobrescribe coordenadas existentes (las de Wikipedia, las que alguien verificó).
  * Datos © colaboradores de OpenStreetMap (ODbL): el mapa del sitio debe mostrar esa atribución.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from agenda import venues as venues_mod
from agenda.dedupe import norm_text
from agenda.http import Disallowed, Fetcher

NOMINATIM = "https://nominatim.openstreetmap.org/search"
DELAY = 1.1  # política de Nominatim: máximo 1 petición por segundo
# izquierda, arriba, derecha, abajo, como lo pide Nominatim
VIEWBOX = f"{venues_mod.BBOX[2]},{venues_mod.BBOX[1]},{venues_mod.BBOX[3]},{venues_mod.BBOX[0]}"
BUILDING_CLASSES = {"amenity", "tourism", "leisure", "building", "shop", "historic", "office", "craft", "man_made"}
MIN_NAME_SCORE = 0.6
SKIP_WORDS = {"de", "del", "la", "el", "los", "las", "y", "en", "sdq", "santo", "domingo", "republica", "dominicana"}
DEFAULT_REPORT = "data/venues_geocodificacion.md"


@dataclass
class Candidate:
    lat: float
    lng: float
    name: str
    osm_type: str
    osm_id: int
    cls: str
    typ: str

    @property
    def ref(self) -> str:
        return f"{self.osm_type}/{self.osm_id}"

    @property
    def link(self) -> str:
        return f"https://www.openstreetmap.org/{self.ref}"


@dataclass
class Row:
    venue_id: str
    venue_name: str
    query: str = ""
    candidates: list = field(default_factory=list)
    pick: Optional[Candidate] = None
    note: str = ""
    distance_m: Optional[float] = None


def params_for(query: str) -> dict:
    return {
        "q": query, "format": "jsonv2", "limit": "3", "countrycodes": "do", "viewbox": VIEWBOX, "bounded": "1",
        "accept-language": "es",
    }


def parse(payload) -> list[Candidate]:
    out = []
    for item in payload if isinstance(payload, list) else []:
        try:
            out.append(Candidate(
                lat=float(item["lat"]), lng=float(item["lon"]), name=str(item.get("display_name") or ""),
                osm_type=str(item["osm_type"]), osm_id=int(item["osm_id"]),
                cls=str(item.get("category") or item.get("class") or ""), typ=str(item.get("type") or ""),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def inside(c: Candidate) -> bool:
    b = venues_mod.BBOX
    return b[0] <= c.lat <= b[1] and b[2] <= c.lng <= b[3]


def precision_for(c: Candidate) -> str:
    if c.cls in BUILDING_CLASSES:
        return "edificio"
    if c.cls == "highway":
        return "calle"
    return "sector"  # place, boundary, landuse...: sirve para la zona, no para el edificio


def name_score(raw: dict, c: Candidate) -> float:
    """Qué parte de las palabras distintivas del lugar (nombre o algún alias) aparece en el resultado."""
    have = set(norm_text(c.name).split())
    best = 0.0
    for text in [raw.get("name", ""), *raw.get("aliases", [])]:
        words = [w for w in norm_text(text).split() if w not in SKIP_WORDS]
        if words:
            best = max(best, sum(w in have for w in words) / len(words))
    return best


def queries_for(raw: dict) -> list[str]:
    tail = "Santo Domingo, República Dominicana"
    qs = [f"{raw['name']}, {tail}"]
    if raw.get("address"):
        qs.append(f"{raw['address']}, {tail}")
    return qs


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def geocode_venue(raw: dict, fetch: Callable[[dict], list]) -> Row:
    row = Row(venue_id=raw["id"], venue_name=raw["name"])
    seen: set[str] = set()
    for query in queries_for(raw):
        row.query = query
        for c in parse(fetch(params_for(query))):
            if c.ref not in seen:
                seen.add(c.ref)
                row.candidates.append(c)
        good = [c for c in row.candidates if inside(c) and name_score(raw, c) >= MIN_NAME_SCORE]
        if good:
            row.pick = good[0]
            return row
    if not row.candidates:
        row.note = "sin resultados"
    elif not any(inside(c) for c in row.candidates):
        row.note = "ningún resultado cae en Santo Domingo"
    else:
        row.note = "el nombre de los resultados no se parece al del lugar: revisar a mano"
    return row


def _apply(raw: dict, row: Row, today: date) -> None:
    c = row.pick
    raw["lat"], raw["lng"] = round(c.lat, 5), round(c.lng, 5)
    raw["precision"] = precision_for(c)
    raw["coord_source"] = f"OpenStreetMap (Nominatim), {c.ref}, consultado el {today.isoformat()}"
    raw["verified"] = False


def _report(rows: list[Row], applied: bool, aborted: Optional[str]) -> str:
    lines = [
        "# Geocodificación de lugares (OpenStreetMap)",
        "",
        "Datos © colaboradores de OpenStreetMap (ODbL). Nada se da por verificado: revisa cada marcador en el mapa.",
        "",
    ]
    if aborted:
        lines += [f"**Se detuvo:** {aborted}", ""]
    lines += ["| Lugar | Resultado | Tipo | Coordenadas | Dif. con la actual | Decisión | Buscar a mano |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        manual = f"[OSM](https://www.openstreetmap.org/search?query={quote(r.venue_name + ', Santo Domingo')})"
        c = r.pick or (r.candidates[0] if r.candidates else None)
        if c is None:
            lines.append(f"| {r.venue_name} | — | — | — | — | {r.note or 'sin consulta'} | {manual} |")
            continue
        dist = f"{r.distance_m:.0f} m" if r.distance_m is not None else "—"
        if r.distance_m is not None:
            decision = "solo comparado"
        elif r.pick:
            decision = "aplicado" if applied else "se aplicaría"
        else:
            decision = r.note
        lines.append(f"| {r.venue_name} | [{c.name[:60]}]({c.link}) | {c.cls}/{c.typ} | {c.lat:.5f}, {c.lng:.5f} "
                     f"| {dist} | {decision} | {manual} |")
    return "\n".join(lines) + "\n"


def run(
    path: str | Path = venues_mod.DEFAULT_PATH,
    fetch: Optional[Callable[[dict], list]] = None,
    aplicar: bool = False,
    revisar: bool = False,
    solo: Optional[list[str]] = None,
    today: Optional[date] = None,
    report_path: Optional[str | Path] = DEFAULT_REPORT,
    log=print,
) -> list[Row]:
    path = Path(path)
    venues_mod.load(path)  # si el archivo ya está mal, que falle antes de consultar nada
    data = json.loads(path.read_text(encoding="utf-8"))
    today = today or date.today()
    fetcher = None
    if fetch is None:
        fetcher = Fetcher(default_delay=DELAY)

        def fetch(params: dict) -> list:
            return fetcher.get(NOMINATIM, delay=DELAY, params=params).json()

    rows: list[Row] = []
    aborted = None
    try:
        for raw in data["venues"]:
            if solo and raw["id"] not in solo:
                continue
            located = raw.get("lat") is not None
            if located and not revisar:
                continue
            try:
                row = geocode_venue(raw, fetch)
            except Disallowed as exc:
                aborted = f"{exc}. Busca a mano con los enlaces de la última columna."
                break
            except Exception as exc:  # noqa: BLE001  (un lugar que falla no tumba a los demás)
                rows.append(Row(raw["id"], raw["name"], note=f"error al consultar: {exc}"))
                continue
            ref = row.pick or (row.candidates[0] if row.candidates else None)
            if located and ref is not None:
                row.distance_m = distance_m(raw["lat"], raw["lng"], ref.lat, ref.lng)
            elif aplicar and row.pick is not None:
                _apply(raw, row, today)
            rows.append(row)
            log(f"{raw['id']:34} {('→ ' + row.pick.ref) if row.pick else row.note}")
    finally:
        if fetcher is not None:
            fetcher.close()
    if aplicar and any(r.pick and r.distance_m is None for r in rows):
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        venues_mod.load(path)  # lo escrito tiene que seguir siendo válido
    if report_path:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_report(rows, aplicar, aborted), encoding="utf-8")
    if aborted:
        log(f"Se detuvo: {aborted}")
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agenda.geocode", description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="guardar en venues.json lo que pase los filtros")
    ap.add_argument("--revisar", action="store_true", help="comparar también las coordenadas existentes")
    ap.add_argument("--solo", action="append", help="id de lugar (repetible)")
    ap.add_argument("--out", default=DEFAULT_REPORT, help="informe en Markdown")
    args = ap.parse_args(argv)
    rows = run(aplicar=args.aplicar, revisar=args.revisar, solo=args.solo, report_path=args.out)
    print(f"{len(rows)} lugar(es) consultados; informe en {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
