"""Exporta los eventos próximos como JSON para el frontend (misma forma que el prototipo)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from agenda import venues as venues_mod
from agenda.db import DB
from agenda.dedupe import dedupe
from agenda.models import Event


def _load_venues(log):
    """Los lugares son un extra: si el archivo falla, los eventos se publican igual."""
    try:
        return venues_mod.default()
    except (OSError, ValueError) as exc:
        if log:
            log(f"AVISO: no se pudo leer agenda/venues.json ({exc}); los eventos salen sin coordenadas")
        return None


def export_json(db: DB, path: str | Path, today: date, log=None, venues=None) -> int:
    """Escribe los eventos próximos, con los repetidos entre fuentes ya unidos. Devuelve cuántos.

    Cada evento cuyo lugar está en agenda/venues.json lleva `venueId`; si el lugar tiene coordenadas, también
    `lat`, `lng` y `geoPrecision`. Junto a events.json se escribe venues.json con los lugares de esos eventos.
    """
    raw = [Event(**p) for p in db.upcoming(today)]
    merged = dedupe(raw)
    book = venues if venues is not None else _load_venues(log)
    events = []
    used: dict[str, venues_mod.Venue] = {}
    unknown: dict[str, int] = {}
    for m in merged:
        pub = m.event.to_public()
        pub["sources"] = [{"srcName": s["name"], "srcUrl": s["url"]} for s in m.sources]
        if book is not None and m.event.venue:
            v = book.find(m.event.venue)
            if v is None:
                unknown[m.event.venue] = unknown.get(m.event.venue, 0) + 1
            else:
                used[v.id] = v
                pub["venueId"] = v.id
                if v.has_coords:
                    pub["lat"], pub["lng"], pub["geoPrecision"] = v.lat, v.lng, v.precision
        events.append(pub)
    if log and book is not None:
        if unknown:
            log(f"{len(unknown)} lugar(es) sin registrar en agenda/venues.json (agrégalos para ubicarlos en el mapa):")
            for name, n in sorted(unknown.items()):
                log(f"   - {name}  ({n} evento{'s' if n != 1 else ''})")
        pending = [v.name for v in used.values() if not v.has_coords]
        if pending:
            log(f"{len(pending)} lugar(es) registrados pero sin coordenadas: {', '.join(sorted(pending))}")
    if log:
        joined = [m for m in merged if len(m.sources) > 1]
        if joined:
            log(f"{len(raw) - len(merged)} repetido(s) unidos en {len(joined)} evento(s):")
            for m in joined:
                log(f"   - {m.event.title}  ({', '.join(s['id'] for s in m.sources)})")
                for c in m.conflicts:
                    log(f"       ! {c}")
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "count": len(events),
        "events": events,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if book is not None:
        places = {
            "generated_at": out["generated_at"],
            "count": len(used),
            "venues": [v.to_public() for v in sorted(used.values(), key=lambda v: v.id)],
        }
        path.with_name("venues.json").write_text(json.dumps(places, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(events)
