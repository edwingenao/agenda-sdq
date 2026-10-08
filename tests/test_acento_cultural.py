"""Acento Cultural con la nota real #61 (17 al 23 de septiembre de 2026) y una respuesta del modelo escrita a mano.

Las pruebas no llaman a la API: la extracción se sustituye por una función falsa. Lo que se prueba es lo que el
adaptador hace con la respuesta: contrastarla con el texto y aplicar las reglas del producto.
"""

from datetime import date
from pathlib import Path

import httpx

from agenda import llm
from agenda.db import DB
from agenda.http import Fetcher
from agenda.sources import SOURCES
from agenda.sources.acento_cultural import AcentoCultural, article_text, build_events, event_block, latest_note

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "acento_cultural_61.html"
HTML = SAMPLE.read_text(encoding="utf-8")
NOTE = "https://acento.com.do/cultura/acento-cultural-61-9753978.html"
TODAY = date(2026, 9, 17)  # el día que salió la nota
TEXT, HEADLINE, PUBLISHED = article_text(HTML)


def item(title, city="Santo Domingo", dates=("2026-09-18",), start_time="", category="Cultura", is_free=None,
         price_min=None, price_max=None, venue="", description=""):
    return {"title": title, "city": city, "venue": venue, "dates": list(dates), "start_time": start_time,
            "category": category, "is_free": is_free, "price_min": price_min, "price_max": price_max,
            "description": description}


# Lo que el modelo podría devolver para la nota 61, con trampas a propósito.
MODEL_OUTPUT = [
    item("CHICAGO: EL MUSICAL", venue="Teatro Nacional Eduardo Brito · Sala Carlos Piantini",
         dates=["2026-09-18", "2026-09-19", "2026-09-20"], category="Teatro",
         description="Musical de Broadway ambientado en el Chicago de los años veinte."),
    item("SEMANA DE BELLAS ARTES 2026 — CIERRE", venue="Sala Aída Bonnelly de Díaz · Teatro Nacional",
         dates=["2026-09-17", "2026-09-18"], start_time="19:00", is_free=True),
    item("LABORATORIO TEATRAL CON WADDYS JÁQUEZ", venue="Conservatorio de Danzas Alina Abreu",
         dates=["2026-09-17", "2026-09-24"], start_time="19:00", category="Teatro"),
    item("Los tres pelos de oro", venue="Sala Nova Teatro · Teatro Cúcara-Mácara",
         dates=["2026-09-19", "2026-09-20"], start_time="18:00", category="Teatro"),
    item("Marteovenus: Regresando a Casa", venue="Casa de Teatro", dates=["2026-09-17"], start_time="21:00",
         category="Música", is_free=False, price_min=1200),  # el precio es del Tributo, no suyo
    item("Múltiple — Solo de impro", venue="Casa de Teatro", dates=["2026-09-18", "2026-09-19"],
         start_time="20:00", category="Teatro"),
    item("Tributo a Gilberto Santa Rosa", venue="Casa de Teatro", dates=["2026-09-18"], start_time="21:00",
         category="Música", is_free=False, price_min=1200),
    item("Celestino Esquerre en concierto", venue="Casa de Teatro", dates=["2026-09-19"], start_time="21:00",
         category="Música", is_free=True),  # la nota no dice que sea gratis
    item("Recorrido por especialistas", city="Baní", venue="Centro Cultural Perelló", dates=["2026-09-17"]),
    item("Conferencia sobre Mario Vargas Llosa", city="Santiago", venue="Centro León", dates=["2026-09-18"]),
    item("12.º Encuentro Iberoamericano de Museos", dates=["2026-09-14", "2026-09-16"]),  # ya pasó
    item("Los tres pelos de oro (otra hora)", dates=["2026-09-19"], start_time="6 pm"),
    item("Sin fecha válida", dates=["el sábado"]),
]


def by_title(events):
    return {e.title: e for e in events}


def built(today=TODAY):
    return by_title(build_events(MODEL_OUTPUT, NOTE, TEXT, today))


# --- la nota real ---


def test_article_text_reads_the_real_note():
    assert HEADLINE == "ACENTO CULTURAL" and PUBLISHED == "2026-09-17"
    assert "17 al 23 de septiembre de 2026" in TEXT and "CHICAGO: EL MUSICAL" in TEXT
    assert "@" not in TEXT  # el correo del autor se quita antes de mandar el texto a la API


def test_sample_has_no_personal_email():
    assert "gmail" not in HTML and "@acento" not in HTML


def test_latest_note_picks_the_highest_number():
    urls = [
        "https://acento.com.do/cultura/acento-cultural-59-9746723.html",
        "https://acento.com.do/cultura/acento-cultural-61-9753978.html",
        "https://acento.com.do/cultura/acento-cultural-60-9750551.html",
        "https://acento.com.do/actualidad/otra-nota-9766330.html",
    ]
    assert latest_note(urls) == NOTE
    assert latest_note(["https://acento.com.do/cultura/otra-9765826.html"]) is None


# --- reglas sobre lo que propone el modelo ---


def test_only_santo_domingo_and_no_past_dates():
    evs = built()
    assert "Recorrido por especialistas" not in evs  # Baní
    assert "Conferencia sobre Mario Vargas Llosa" not in evs  # Santiago
    assert "12.º Encuentro Iberoamericano de Museos" not in evs  # 14 al 16, antes de la nota
    assert "Sin fecha válida" not in evs
    assert len(evs) == 9


def test_everything_needs_review_and_links_to_the_note():
    for e in build_events(MODEL_OUTPUT, NOTE, TEXT, TODAY):
        assert e.needs_review and e.source == "acento_cultural" and e.source_name == "Acento Cultural"
        assert e.url.startswith(NOTE + "#")
    assert len({e.key for e in build_events(MODEL_OUTPUT, NOTE, TEXT, TODAY)}) == 9


def test_price_must_be_in_the_events_own_block():
    evs = built()
    assert (evs["Tributo a Gilberto Santa Rosa"].is_free, evs["Tributo a Gilberto Santa Rosa"].price_min) == (False, 1200)
    marte = evs["Marteovenus: Regresando a Casa"]
    assert (marte.is_free, marte.price_min) == (None, None)  # el RD$1,200 de la nota es del Tributo


def test_free_only_if_the_block_says_so():
    evs = built()
    bellas = evs["SEMANA DE BELLAS ARTES 2026 — CIERRE"]
    assert bellas.is_free is True and bellas.price_min == 0  # "Entrada gratuita hasta completar aforo"
    assert evs["Celestino Esquerre en concierto"].is_free is None  # el modelo dijo gratis; la nota no


def test_time_is_kept_only_when_valid_and_single():
    evs = built()
    assert evs["CHICAGO: EL MUSICAL"].start_time is None  # 8:30 p. m., pero el domingo a las 7:00
    assert evs["Tributo a Gilberto Santa Rosa"].start_time == "21:00"
    assert evs["Los tres pelos de oro (otra hora)"].start_time is None  # "6 pm" no es HH:MM


def test_dates_sessions_and_ranges():
    evs = built()
    assert evs["CHICAGO: EL MUSICAL"].dates == ["2026-09-18", "2026-09-19", "2026-09-20"]
    assert evs["LABORATORIO TEATRAL CON WADDYS JÁQUEZ"].to_public()["end"] == "2026-09-24"


def test_running_range_starts_today():
    evs = by_title(build_events(MODEL_OUTPUT, NOTE, TEXT, date(2026, 9, 21)))
    assert evs["LABORATORIO TEATRAL CON WADDYS JÁQUEZ"].dates == ["2026-09-21", "2026-09-24"]
    assert "Tributo a Gilberto Santa Rosa" not in evs


def test_a_note_from_weeks_ago_gives_nothing():
    assert build_events(MODEL_OUTPUT, NOTE, TEXT, date(2026, 10, 7)) == []


def test_bad_model_output_is_ignored():
    assert build_events([None, "texto", {"title": ""}, item("Sin ciudad", city="")], NOTE, TEXT, TODAY) == []


def test_category_and_zone():
    evs = built()
    assert evs["CHICAGO: EL MUSICAL"].category == "Teatro" and evs["CHICAGO: EL MUSICAL"].zone == "Plaza de la Cultura"
    assert evs["Tributo a Gilberto Santa Rosa"].zone == "Ciudad Colonial"


def test_event_block_stops_at_the_next_event():
    block = event_block("Marteovenus: Regresando a Casa", TEXT, others=["Múltiple — Solo de impro"])
    assert "jueves 17" in block and "1,200" not in block and "multiple" not in block


# --- la fuente completa ---


def _fetcher(pages):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\n")
        body = pages.get(str(req.url))
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)

    return Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)


DAILY = f"<urlset><url><loc>https://acento.com.do/seccion/cultura.html</loc></url><url><loc>{NOTE}</loc></url></urlset>"


def test_run_without_ai_publishes_nothing_and_says_why(monkeypatch):
    monkeypatch.delenv("AGENDA_LLM", raising=False)
    logs = []
    src = AcentoCultural(_fetcher({}), DB(":memory:"), TODAY, "2026-09-17T12:00:00+00:00", log=logs.append)
    assert src.run() == [] and any("desactivada" in line for line in logs)


def test_run_finds_the_note_extracts_and_skips_it_when_unchanged(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    calls = []

    def fake_extract(text, url, today, title=""):
        calls.append((url, title))
        assert "CHICAGO: EL MUSICAL" in text
        return MODEL_OUTPUT

    pages = {"https://acento.com.do/sitemaps/sitemaps-daily.xml": DAILY, NOTE: HTML}
    db, logs = DB(":memory:"), []
    src = AcentoCultural(_fetcher(pages), db, TODAY, "2026-09-17T12:00:00+00:00", log=logs.append)
    src.extract = fake_extract
    evs = src.run()
    assert len(evs) == 9 and calls == [(NOTE, "ACENTO CULTURAL")]
    assert any("el modelo propuso 13, 9 pasan" in line for line in logs)

    again = AcentoCultural(_fetcher(pages), db, TODAY, "2026-09-18T12:00:00+00:00", log=logs.append)
    again.extract = fake_extract
    assert again.run() == [] and len(calls) == 1  # misma nota: no se vuelve a pagar la extracción


def test_run_falls_back_to_the_full_sitemap(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    pages = {
        "https://acento.com.do/sitemaps/sitemaps-daily.xml": "<urlset></urlset>",
        "https://acento.com.do/sitemaps/sitemaps-index.xml":
            "<sitemapindex><sitemap><loc>https://acento.com.do/sitemaps/acento-2.txt</loc></sitemap>"
            "<sitemap><loc>https://acento.com.do/sitemaps/acento-15.txt</loc></sitemap></sitemapindex>",
        "https://acento.com.do/sitemaps/acento-15.txt":
            "https://acento.com.do/cultura/acento-cultural-60-9750551.html\n" + NOTE + "\n",
        NOTE: HTML,
    }
    src = AcentoCultural(_fetcher(pages), DB(":memory:"), TODAY, "2026-09-17T12:00:00+00:00", log=lambda *_: None)
    src.extract = lambda text, url, today, title="": MODEL_OUTPUT
    assert len(src.run()) == 9


def test_registered_and_last_in_priority():
    from agenda.dedupe import SOURCE_PRIORITY

    assert SOURCES["acento_cultural"] is AcentoCultural
    assert SOURCE_PRIORITY[-1] == "acento_cultural"


# --- llm.extract_events con un cliente de Anthropic falso (sin red) ---


def _fake_anthropic(monkeypatch, text, stop_reason="end_turn"):
    import sys
    import types

    sent = {}

    class Block:
        type = "text"

        def __init__(self, t):
            self.text = t

    class Messages:
        def create(self, **kwargs):
            sent.update(kwargs)
            return types.SimpleNamespace(stop_reason=stop_reason, content=[Block(text)])

    module = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(messages=Messages()))
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("AGENDA_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba")
    monkeypatch.delenv("AGENDA_LLM_MODEL", raising=False)
    return sent


def test_extract_events_asks_for_structured_output(monkeypatch):
    sent = _fake_anthropic(monkeypatch, '{"events": [{"title": "X"}]}')
    assert llm.extract_events("texto", NOTE, TODAY, "ACENTO CULTURAL") == [{"title": "X"}]
    assert sent["model"] == "claude-haiku-4-5"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "ACENTO CULTURAL" in sent["messages"][0]["content"]


def test_extract_events_rejects_truncated_or_refused_answers(monkeypatch):
    _fake_anthropic(monkeypatch, '{"events": [', stop_reason="max_tokens")
    assert llm.extract_events("texto", NOTE, TODAY) is None
