"""Pruebas de los adaptadores con HTML SINTÉTICO armado a partir de lo que mostraron las páginas reales.
Prueban la lógica; no garantizan que el marcado real coincida (para eso está `python -m agenda inspect`)."""

import json
from datetime import date

import httpx

from agenda.db import DB
from agenda.export import export_json
from agenda.http import Disallowed, Fetcher
from agenda.models import Event
from agenda.sources.cce import CentroCulturalEspana, extract_links
from agenda.sources.cce import parse_detail as cce_detail
from agenda.sources.teatro_nacional import TeatroNacional
from agenda.sources.teatro_nacional import parse_detail as tn_detail
from agenda.sources.zona_colonial import parse_listing

TODAY = date(2026, 10, 5)
NOW = "2026-10-05T12:00:00+00:00"

TN_HTML = """<html><body><nav><a href="/">Inicio</a></nav><main>
<h1>Wagner / Molina</h1>
<div><span>Fecha:</span> <span>7 de octubre, 2026</span></div>
<div>Sala: Sala Carlos Piantini</div>
<div>Conciertos</div>
<table><tr><td>Platea</td><td>RD$2,290.00</td></tr><tr><td>Balcón Filas A-C</td><td>RD$1,730.00</td></tr></table>
<a href="https://boleteria.com.do/evento/wagner">Compre sus boletas aqui</a>
<p>Temporada Sinfónica 2026 de la Orquesta Sinfónica Nacional en la Sala Carlos Piantini.</p>
</main></body></html>"""

ZONA_HTML = """<html><body><nav><a href="/actividades/">Actividades</a><a href="/contacto/">Contacto</a></nav>
<section class="lista">
<article><span>OCT 06</span><h3><a href="https://zonacolonial.do/actividades/el-desencanto/">El desencanto (1976)</a></h3>
<p>Casa de Teatro, Arzobispo Meriño #110</p><span>Entrada Gratis</span><a href="#">Agendar</a><a href="https://zonacolonial.do/mapa/1/">Ver Mapa</a></article>
<article><span>OCT 16</span><h3><a href="https://zonacolonial.do/actividades/tributo-rbd/">TRIBUTO (RBD)</a></h3>
<p>Casa de Teatro, Arzobispo Meriño #110</p><span>$1200</span><a href="#">Agendar</a></article>
<article><span>SEP 20</span><h3><a href="https://zonacolonial.do/actividades/pasado/">Evento pasado</a></h3>
<p>Quinta Dominica</p><span>Gratis</span></article>
<article><span>NOV 28</span><h3><a href="https://zonacolonial.do/actividades/shalondy/">SHALONDY</a></h3>
<p>Casa de Teatro</p><span>$500</span></article>
</section></body></html>"""

CCE_HTML = """<html><body><header><a href="/">Inicio</a></header><main>
<h1>La construcción narrativa de la novela: El narrador, el narratario y los personajes</h1>
<span>Formación</span>
<p>Imparte Pedro Antonio Valdez. Dirigido a todo público, con entrada libre hasta completar aforo.</p>
<div>Fechas</div><div>17/Oct/2026 24/Oct/2026 31/Oct/2026 07/Nov/2026</div>
<div>Horario: 10 am a 1 pm</div>
<div>Lugar: Centro Cultural de España</div>
<div>Precio: Gratuito (Entrada libre hasta completar aforo)</div>
<div>Cierre de inscripciones: 14 DE octubre DE 2026</div>
<h2>Eventos relacionados</h2><div>25/Dic/2026 Otra cosa</div>
</main></body></html>"""


def test_teatro_nacional_detail():
    item = {"event-category": [22], "title": {"rendered": "Wagner / Molina"}}
    ev = tn_detail(TN_HTML, "https://teatronacional.gob.do/events/wagner-molina/", item, TODAY)
    assert ev.dates == ["2026-10-07"]
    assert ev.venue == "Sala Carlos Piantini, Teatro Nacional"
    assert ev.zone == "Plaza de la Cultura"
    assert (ev.is_free, ev.price_min, ev.price_max) == (False, 1730, 2290)
    assert ev.category == "Música"
    assert ev.ticket_url == "https://boleteria.com.do/evento/wagner"
    assert not ev.needs_review
    assert ev.to_public()["price"] == 1730


def test_teatro_nacional_free_category():
    html = TN_HTML.replace("RD$2,290.00", "").replace("RD$1,730.00", "")
    ev = tn_detail(html, "https://teatronacional.gob.do/events/x/", {"event-category": [18, 22]}, TODAY)
    assert ev.is_free is True and ev.to_public()["price"] == 0


def test_teatro_nacional_no_date_returns_none():
    assert tn_detail("<html><body><h1>Sin fecha</h1></body></html>", "u", {}, TODAY) is None


def test_zona_colonial_listing():
    evs = parse_listing(ZONA_HTML, "https://zonacolonial.do/actividades/", TODAY)
    by_title = {e.title: e for e in evs}
    assert set(by_title) == {"El desencanto (1976)", "TRIBUTO (RBD)", "SHALONDY"}  # el pasado se omite
    free = by_title["El desencanto (1976)"]
    assert free.dates == ["2026-10-06"] and free.is_free is True
    assert free.venue == "Casa de Teatro" and free.zone == "Ciudad Colonial"
    assert by_title["TRIBUTO (RBD)"].price_min == 1200
    assert by_title["SHALONDY"].dates == ["2026-11-28"]


def test_zona_colonial_zero_cards_is_empty_not_error():
    assert parse_listing("<html><body><p>nada</p></body></html>", "https://zonacolonial.do/actividades/", TODAY) == []


def test_cce_detail():
    ev = cce_detail(CCE_HTML, "https://ccesd.aecid.es/w/novela", TODAY)
    assert ev.dates == ["2026-10-17", "2026-10-24", "2026-10-31", "2026-11-07"]  # sin cierre de inscripción ni relacionados
    assert ev.start_time == "10:00"
    assert ev.venue == "Centro Cultural de España"
    assert ev.is_free is True
    assert "formacion" in ev.tags
    assert not ev.needs_review
    assert ev.to_public()["sessions"] == ev.dates


def test_cce_formacion_without_price_line_is_free():
    """Confirmado por Edwin (7 oct 2026): los cursos de Formación del CCE son gratuitos aunque la página no lo diga."""
    html = CCE_HTML.replace("Precio: Gratuito (Entrada libre hasta completar aforo)", "")
    ev = cce_detail(html, "https://ccesd.aecid.es/w/novela", TODAY)
    assert "formacion" in ev.tags and ev.is_free is True and ev.price_min == 0


def test_cce_formacion_with_a_price_keeps_the_price():
    html = CCE_HTML.replace("Precio: Gratuito (Entrada libre hasta completar aforo)", "Precio: RD$1,500")
    ev = cce_detail(html, "https://ccesd.aecid.es/w/novela", TODAY)
    assert ev.is_free is False and ev.price_min == 1500


def test_cce_event_that_is_not_formacion_stays_unconfirmed():
    html = CCE_HTML.replace("Precio: Gratuito (Entrada libre hasta completar aforo)", "").replace("Formación", "Exposición")
    html = html.replace("con entrada libre hasta completar aforo", "")
    ev = cce_detail(html, "https://ccesd.aecid.es/w/expo", TODAY)
    assert "formacion" not in ev.tags and ev.is_free is None


def test_cce_extract_links_skips_portlet_urls():
    html = """<a href="/w/uno">1</a><a href="/w/dos?x=1#frag">2</a><a href="/w/uno">dup</a>
    <a href="/c/portal/login">login</a><a href="/w/tres?p_p_id=abc">3</a><a href="https://otro.com/w/cuatro">4</a>"""
    assert extract_links(html, "https://ccesd.aecid.es/eventos/buscador-de-eventos") == [
        "https://ccesd.aecid.es/w/uno",
        "https://ccesd.aecid.es/w/dos?x=1",
    ]


# --- orquestación con un fetcher falso ---------------------------------------------------------

class FakeResponse:
    def __init__(self, body):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self._body = body

    def json(self):
        return self._body if not isinstance(self._body, str) else json.loads(self._body)


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, delay=None, params=None):
        self.calls.append(url)
        return FakeResponse(self.pages[url])


def test_teatro_nacional_run_skips_unchanged_pages_and_exports(tmp_path):
    url = "https://teatronacional.gob.do/events/wagner-molina/"
    api = "https://teatronacional.gob.do/wp-json/wp/v2/event"
    pages = {api: [{"link": url, "title": {"rendered": "Wagner / Molina"}, "event-category": [22]}], url: TN_HTML}
    db = DB(":memory:")

    first = TeatroNacional(FakeFetcher(pages), db, TODAY, NOW, log=lambda *_: None).run()
    assert len(first) == 1
    assert db.upsert_event(first[0], NOW) == "new"

    second = TeatroNacional(FakeFetcher(pages), db, TODAY, NOW, log=lambda *_: None).run()
    assert second == []  # la página no cambió: no se reprocesa

    out = tmp_path / "events.json"
    assert export_json(db, out, TODAY) == 1
    data = json.loads(out.read_text())
    assert data["events"][0]["title"] == "Wagner / Molina" and data["events"][0]["price"] == 1730


def test_cce_run_prioritizes_unseen_and_respects_max_details():
    listing = "https://ccesd.aecid.es/eventos/buscador-de-eventos"
    html = "".join(f'<a href="/w/e{i}">E{i}</a>' for i in range(5))
    pages = {listing: html}
    for i in range(5):
        pages[f"https://ccesd.aecid.es/w/e{i}"] = CCE_HTML.replace("narrativa", f"narrativa{i}")
    db = DB(":memory:")
    fetcher = FakeFetcher(pages)
    evs = CentroCulturalEspana(fetcher, db, TODAY, NOW, max_details=2, log=lambda *_: None).run()
    assert len(evs) == 2
    assert len(fetcher.calls) == 3  # 1 listado + 2 detalles


def test_past_events_not_exported():
    db = DB(":memory:")
    past = Event(source="x", source_name="X", url="u1", title="Pasado", dates=["2026-09-01"])
    fut = Event(source="x", source_name="X", url="u2", title="Futuro", dates=["2026-10-20"])
    db.upsert_event(past, NOW)
    db.upsert_event(fut, NOW)
    assert [p["title"] for p in db.upcoming(TODAY)] == ["Futuro"]


def test_db_detects_updates():
    db = DB(":memory:")
    ev = Event(source="x", source_name="X", url="u", title="A", dates=["2026-10-20"])
    assert db.upsert_event(ev, NOW) == "new"
    assert db.upsert_event(ev, NOW) == "same"
    ev.title = "B"
    assert db.upsert_event(ev, NOW) == "updated"


# --- robots.txt y cortesía ---------------------------------------------------------------------

ROBOTS = """User-agent: GPTBot
Crawl-delay: 30
Disallow: /search

User-agent: *
Disallow: /search
Disallow: /c/
Disallow: *p_p_id=
Disallow: *p_auth=
"""


def _fetcher(handler, sleeps=None, clock=None):
    return Fetcher(
        default_delay=2,
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=clock or (lambda: 0.0),
    )


def test_robots_wildcards_block_portlet_urls():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text="ok")

    f = _fetcher(handler)
    assert f.allowed("https://ccesd.aecid.es/w/evento")
    assert not f.allowed("https://ccesd.aecid.es/w/evento?p_p_id=abc")
    assert not f.allowed("https://ccesd.aecid.es/c/portal/login")
    try:
        f.get("https://ccesd.aecid.es/search")
        raise AssertionError("debió lanzar Disallowed")
    except Disallowed:
        pass


def test_fetcher_waits_between_requests_to_same_host():
    sleeps = []

    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text="ok")

    f = _fetcher(handler, sleeps)
    f.get("https://example.org/a")
    f.get("https://example.org/b")
    assert sleeps == [2.0]


def test_fetcher_treats_robots_5xx_as_disallowed():
    f = _fetcher(lambda req: httpx.Response(503))
    try:
        f.get("https://example.org/a")
        raise AssertionError("debió lanzar Disallowed")
    except Disallowed:
        pass
