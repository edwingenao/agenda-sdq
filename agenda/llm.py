"""Extracción de respaldo con Claude, SOLO cuando el adaptador no logra leer una página.

Se activa con AGENDA_LLM=1 y ANTHROPIC_API_KEY. Requiere: pip install anthropic
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

PROMPT = """Eres un extractor de eventos culturales de Santo Domingo, República Dominicana.
Hoy es {today}. Del texto de la página devuelve SOLO un objeto JSON (sin explicación) con estas claves:
title (string), dates (lista de fechas ISO YYYY-MM-DD; si es un rango, primera y última),
start_time ("HH:MM" en 24 h o null), venue (string), category (una de: Música, Teatro, Cine, Arte, Danza, Cultura),
is_free (true, false o null si no se dice), price_min (entero RD$ o null), price_max (entero RD$ o null).
No inventes datos: usa null cuando el texto no lo diga. Si la página no describe un evento, devuelve {{"title": null}}.

URL: {url}
TEXTO:
{text}
"""


def available() -> bool:
    return os.environ.get("AGENDA_LLM") == "1" and bool(os.environ.get("ANTHROPIC_API_KEY"))


def extract(lines: list[str], url: str, today: date) -> dict | None:
    if not available():
        return None
    import anthropic  # import tardío: es opcional

    client = anthropic.Anthropic()
    model = os.environ.get("AGENDA_LLM_MODEL", "claude-haiku-4-5-20251001")
    text = "\n".join(lines[:150])[:12000]
    msg = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": PROMPT.format(today=today.isoformat(), url=url, text=text)}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("title") or not data.get("dates"):
        return None
    return data
