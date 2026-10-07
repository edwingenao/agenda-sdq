"""Exporta los eventos próximos como JSON para el frontend (misma forma que el prototipo)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from agenda.db import DB
from agenda.models import Event


def export_json(db: DB, path: str | Path, today: date) -> int:
    events = [Event(**p).to_public() for p in db.upcoming(today)]
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
