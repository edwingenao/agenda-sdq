"""Ticketmax con la portada y una página de evento reales (7 oct 2026), recortadas en samples/."""

import json
from datetime import date
from pathlib import Path

import httpx

from agenda.db import DB
from agenda.http import Fetcher
from agenda.sources import SOURCES
from agenda.sources.ticketmax import Ticketmax, clean_title, event_ld, parse_cards, parse_event

S = Path(__file__).resolve().parent.parent / "samples"
HOME = (S / "ticketmax_portada.html").read_text(encoding="utf-8")
EVENT = (S / "ticketmax_evento_253550.html").read_text(encoding="utf-8")
TODAY = date(2026, 10, 7)
ROBIN = "https://ticketmax.org/evento/253550/"


def card(url=ROBIN, city="Santo Domingo", venue="Casa de Teatro", cats=("comedia",), title="robin hood"):
    return {"url": url, "city": city, "venue": venue, "cats": list(cats), "title": title}


def with_ld(**over):
    """La página real con campos del JSON-LD cambiados."""
    ld = event_ld(EVENT)
    ld.update(over)
    return f'<html><head><script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head></html>'


# --- portada ---


def test_cards_from_the_real_home_page():
    cards = parse_cards(HOME)
    assert len(cards) == 68
    assert sum(c["city"] == "Santo Domingo" for c in cards) == 56
    first = cards[0]
    assert first == {"url": "https://ticketmax.org/evento/264180/", "city": "Santo Domingo", "venue": "Velvet Room",
                     "cats": ["conciertos"], "title": "techy: una temporada chula"}
    assert all(c["url"].startswith("https://ticketmax.org/evento/") and c["url"].endswith("/") for c in cards)


# --- página de evento ---


def test_real_event_page():
    ev = parse_event(card(), EVENT, TODAY)
    assert ev.title == "FDT 10x10 | LA LEYENDA DE ROBIN HOOD"
    assert ev.dates == ["2026-11-06"] and ev.start_time == "20:30"
    assert (ev.is_free, ev.price_min, ev.price_max) == (False, 800, None)
    assert ev.venue == "Casa de Teatro" and ev.zone == "Ciudad Colonial"
    assert ev.category == "Teatro"  # data-cats "comedia"
    assert ev.url == ev.ticket_url == ROBIN and ev.source_name == "Ticketmax"
    assert ev.description.startswith("Convertido en el forajido") and len(ev.description) <= 280
    assert not ev.needs_review


def test_clean_title():
    assert clean_title("FDT 10x10 | LA LEYENDA DE ROBIN HOOD | | 8:30 PM | Viernes 6 Noviembre 2026") == \
        "FDT 10x10 | LA LEYENDA DE ROBIN HOOD"
    assert clean_title("LA GRANJA DE ZENÓN: LA BUSQUEDA DEL TESORO | 2:00 PM | Domingo 8 Noviembre 2026") == \
        "LA GRANJA DE ZENÓN: LA BUSQUEDA DEL TESORO"
    assert clean_title("Concierto sin sufijo") == "Concierto sin sufijo"


def test_time_is_converted_to_santo_domingo():
    ev = parse_event(card(), with_ld(startDate="2026-11-07T00:30:00Z"), TODAY)  # 8:30 p. m. del 6 en SD
    assert ev.dates == ["2026-11-06"] and ev.start_time == "20:30"


def test_midnight_means_no_time():
    assert parse_event(card(), with_ld(startDate="2026-11-06T00:00:00-04:00"), TODAY).start_time is None


def test_price_range_and_free():
    ev = parse_event(card(), with_ld(offers={"lowPrice": "1500.00", "highPrice": "3000.00", "priceCurrency": "DOP"}), TODAY)
    assert (ev.is_free, ev.price_min, ev.price_max) == (False, 1500, 3000)
    ev = parse_event(card(), with_ld(offers={"lowPrice": "0.00", "highPrice": "0.00", "priceCurrency": "DOP"}), TODAY)
    assert (ev.is_free, ev.price_min) == (True, 0)


def test_missing_or_foreign_price_is_unconfirmed():
    assert parse_event(card(), with_ld(offers=None), TODAY).is_free is None
    ev = parse_event(card(), with_ld(offers={"lowPrice": "20", "priceCurrency": "USD"}), TODAY)
    assert (ev.is_free, ev.price_min) == (None, None)


def test_other_cities_and_past_events_are_dropped():
    santiago = with_ld(location={"@type": "Place", "name": "Gran Teatro del Cibao",
                                 "address": {"addressLocality": "Santiago"}})
    assert parse_event(card(), santiago, TODAY) is None
    assert parse_event(card(), with_ld(startDate="2026-10-01T20:00:00-04:00"), TODAY) is None
    assert parse_event(card(), "<html></html>", TODAY) is None  # sin JSON-LD


def test_city_falls_back_to_the_card():
    no_city = with_ld(location={"@type": "Place", "name": "Velvet Room"})
    assert parse_event(card(venue="Velvet Room"), no_city, TODAY).venue == "Velvet Room"
    assert parse_event(card(city="Santiago"), no_city, TODAY) is None


def test_category_from_the_card():
    assert parse_event(card(cats=["conciertos"]), EVENT, TODAY).category == "Música"
    assert parse_event(card(cats=["cata"]), EVENT, TODAY).category == "Gastronomía"


# --- la fuente completa ---


def test_run_reads_only_santo_domingo_and_skips_unchanged_pages():
    home = (
        '<div class="tm-event-card" data-city="Santo Domingo" data-venue="Casa de Teatro" data-cats="comedia">'
        f'<a href="{ROBIN}fdt-10x10-la-leyenda-de-robin-hood/">x</a></div>'
        '<div class="tm-event-card" data-city="Santiago" data-venue="Gran Teatro" data-cats="conciertos">'
        '<a href="https://ticketmax.org/evento/2/">x</a></div>'
        '<div class="tm-event-card" data-city="Santo Domingo" data-venue="Hotel" data-cats="congresos">'
        '<a href="https://ticketmax.org/evento/3/">x</a></div>'
    )
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /wp-admin/\n")
        calls.append(str(req.url))
        return httpx.Response(200, text=home if str(req.url) == "https://ticketmax.org/" else EVENT)

    db = DB(":memory:")
    f = Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)
    evs = Ticketmax(f, db, TODAY, "2026-10-07T12:00:00+00:00", log=lambda *_: None).run()
    assert [e.url for e in evs] == [ROBIN]
    assert calls == ["https://ticketmax.org/", ROBIN]  # ni Santiago ni el congreso se piden

    again = Ticketmax(f, db, TODAY, "2026-10-08T12:00:00+00:00", log=lambda *_: None).run()
    assert again == []  # la página no cambió: no se reprocesa


def test_registered():
    assert SOURCES["ticketmax"] is Ticketmax
