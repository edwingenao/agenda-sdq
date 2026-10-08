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


MODEL = "claude-haiku-4-5"

PROMPT_MANY = """Eres un extractor de eventos culturales para una agenda de Santo Domingo, República Dominicana.
Hoy es {today}. El texto es una agenda semanal de prensa ({title}); puede listar eventos de varias ciudades.

Devuelve un evento por cada función, concierto, exposición u obra con fecha que el texto anuncie. Reglas:
- city: la ciudad tal como la indica el texto o su sección ("Santo Domingo", "Santiago", "Baní"...). Si no se sabe, "".
- dates: fechas ISO YYYY-MM-DD. Funciones en días sueltos: una fecha por día. Rango ("del 17 al 23", "hasta el 24"): solo
  primera y última; si solo dice "hasta", la primera es la del inicio de la semana de la agenda.
- start_time: "HH:MM" en 24 h solo si el texto da UNA hora para todas las fechas; si cambia según el día o no se dice, "".
- is_free: true solo si el texto dice gratis, gratuito o entrada libre; false si da un precio; null si no dice nada.
- price_min / price_max: montos en RD$ que aparezcan en el texto, o null.
- description: una frase corta, con palabras del texto, de qué es.
No inventes nada. No incluyas libros, reseñas, encuentros ya celebrados ni actividades sin fecha.

URL: {url}
TEXTO:
{text}
"""

EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "city": {"type": "string"},
                    "venue": {"type": "string"},
                    "dates": {"type": "array", "items": {"type": "string"}},
                    "start_time": {"type": "string"},
                    "category": {"type": "string", "enum": ["Música", "Teatro", "Danza", "Cine", "Arte", "Cultura"]},
                    "is_free": {"type": ["boolean", "null"]},
                    "price_min": {"type": ["integer", "null"]},
                    "price_max": {"type": ["integer", "null"]},
                    "description": {"type": "string"},
                },
                "required": ["title", "city", "venue", "dates", "start_time", "category", "is_free",
                             "price_min", "price_max", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


def available() -> bool:
    return os.environ.get("AGENDA_LLM") == "1" and bool(os.environ.get("ANTHROPIC_API_KEY"))


def extract(lines: list[str], url: str, today: date) -> dict | None:
    if not available():
        return None
    import anthropic  # import tardío: es opcional

    client = anthropic.Anthropic()
    model = os.environ.get("AGENDA_LLM_MODEL", MODEL)
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


def extract_events(text: str, url: str, today: date, title: str = "") -> list[dict] | None:
    """Todos los eventos de una agenda de prensa, como lista de dicts (forma de EVENTS_SCHEMA).

    None si la extracción no está activada o la respuesta no sirve. La salida estructurada garantiza un JSON con la
    forma del esquema, pero no que los datos sean ciertos: quien llama debe contrastarlos con el texto.
    """
    if not available():
        return None
    import anthropic  # import tardío: es opcional

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("AGENDA_LLM_MODEL", MODEL),
        max_tokens=8000,
        messages=[{"role": "user", "content": PROMPT_MANY.format(
            today=today.isoformat(), title=title, url=url, text=text[:30000])}],
        output_config={"format": {"type": "json_schema", "schema": EVENTS_SCHEMA}},
    )
    if msg.stop_reason != "end_turn":  # max_tokens o refusal: JSON incompleto o sin datos
        return None
    raw = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    events = data.get("events") if isinstance(data, dict) else None
    return events if isinstance(events, list) else None
