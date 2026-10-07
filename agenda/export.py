"""Exporta los eventos próximos como JSON para el frontend (misma forma que el prototipo)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from agenda.db import DB
from agenda.dedupe import dedupe
from agenda.models import Event


def export_json(db: DB, path: str | Path, today: date, log=None) -> int:
    """Escribe los eventos próximos, con los repetidos entre fuentes ya unidos. Devuelve cuántos."""
    raw = [Event(**p) for p in db.upcoming(today)]
    merged = dedupe(raw)
    events = []
    for m in merged:
        pub = m.event.to_public()
        pub["sources"] = [{"srcName": s["name"], "srcUrl": s["url"]} for s in m.sources]
        events.append(pub)
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
    return len(events)
