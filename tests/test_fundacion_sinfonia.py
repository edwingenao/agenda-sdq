"""Fundación Sinfonía con dos páginas reales (7 oct 2026), recortadas en samples/."""

from datetime import date
from pathlib import Path

import httpx

from agenda.db import DB
from agenda.dedupe import dedupe
from agenda.http import Fetcher
from agenda.models import Event
from agenda.sources import SOURCES
from agenda.sources.fundacion_sinfonia import FundacionSinfonia, _price, parse_page, sitemap_urls

S = Path(__file__).resolve().parent.parent / "samples"
MAHLER = (S / "sinfonia_mahler.html").read_text(encoding="utf-8")
TRIO = (S / "sinfonia_trio_vibrart.html").read_text(encoding="utf-8")
URL = "https://sinfonia.org.do/agenda/mahler-resurreccion-gala-de-aniversarios/"
TODAY = date(2026, 10, 7)


def test_real_page_with_prices():
    ev = parse_page(MAHLER, URL, TODAY)
    assert ev.title == "Mahler: Resurrección | Gala de aniversarios"
    assert ev.dates == ["2026-11-04"] and ev.start_time == "20:30"
    assert (ev.is_free, ev.price_min, ev.price_max) == (False, 2290, 5640)  # Balcón 2,290 a Platea 5,640
    assert ev.venue == "Sala Carlos Piantini del Teatro Nacional" and ev.zone == "Plaza de la Cultura"
    assert ev.category == "Música" and ev.source_name == "Fundación Sinfonía"
    assert ev.description.startswith("No te pierdas") and len(ev.description) <= 280


def test_real_free_page():
    ev = parse_page(TRIO, "https://sinfonia.org.do/agenda/trio-vibrart/", date(2026, 6, 1))
    assert ev.dates == ["2026-06-14"] and ev.start_time == "19:00"
    assert (ev.is_free, ev.price_min) == (True, 0)  # "Entradas libres de costo"


def test_past_events_are_dropped():
    assert parse_page(TRIO, "https://sinfonia.org.do/agenda/trio-vibrart/", TODAY) is None


def test_season_umbrella_is_skipped():
    season = MAHLER.replace(">Concierto<", ">Temporada<", 1)
    assert parse_page(season, URL, TODAY) is None


def test_price_rules():
    assert _price(["Platea: 5,640.00 y 3,405.00", "Balcón: 4,525.00 y 2,290.00"]) == (False, 2290, 5640)
    assert _price(["Boletas: RD$800"]) == (False, 800, None)
    assert _price(["Boletas disponibles desde el 1 de junio de 2026 en la boletería"]) == (None, None, None)
    assert _price(["Boletas libres de costo disponibles en la boletería"]) == (True, 0, None)
    assert _price(["Un concierto especial"]) == (None, None, None)


def test_sitemap_keeps_only_recent_pages():
    xml = (
        "<urlset>"
        "<url><loc>https://sinfonia.org.do/agenda/vieja/</loc><lastmod>2025-01-10T10:00:00+00:00</lastmod></url>"
        "<url><loc>https://sinfonia.org.do/agenda/nueva/</loc><lastmod>2026-09-03T10:00:00+00:00</lastmod></url>"
        "<url><loc>https://sinfonia.org.do/eventos/</loc><lastmod>2026-09-03T10:00:00+00:00</lastmod></url>"
        "</urlset>"
    )
    assert sitemap_urls(xml, TODAY) == ["https://sinfonia.org.do/agenda/nueva/"]


def test_merging_with_teatro_nacional_fills_in_the_time():
    tn = Event(source="teatro_nacional", source_name="Teatro Nacional",
               url="https://teatronacional.gob.do/events/mahler-resurrecion/", title="Mahler Resurreción",
               dates=["2026-11-04"], venue="Sala Carlos Piantini, Teatro Nacional", is_free=False, price_min=2290)
    merged = dedupe([tn, parse_page(MAHLER, URL, TODAY)])
    assert len(merged) == 1
    ev = merged[0].event
    assert ev.source == "teatro_nacional" and ev.start_time == "20:30"  # la hora viene de la Fundación


def test_run_reads_recent_pages_and_skips_unchanged():
    sitemap = f"<urlset><url><loc>{URL}</loc><lastmod>2026-09-03T10:00:00+00:00</lastmod></url></urlset>"
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        calls.append(str(req.url))
        return httpx.Response(200, text=sitemap if req.url.path.endswith(".xml") else MAHLER)

    db = DB(":memory:")
    f = Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)
    evs = FundacionSinfonia(f, db, TODAY, "2026-10-07T12:00:00+00:00", log=lambda *_: None).run()
    assert [e.url for e in evs] == [URL]
    assert FundacionSinfonia(f, db, TODAY, "2026-10-08T12:00:00+00:00", log=lambda *_: None).run() == []


def test_registered():
    assert SOURCES["fundacion_sinfonia"] is FundacionSinfonia
