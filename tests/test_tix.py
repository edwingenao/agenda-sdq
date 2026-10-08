"""TIX con dos páginas reales de su API (7 oct 2026), guardadas sin datos de los organizadores en samples/."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from agenda.db import DB
from agenda.http import Fetcher
from agenda.sources import SOURCES
from agenda.sources.tix import FIELDS, Tix, parse_item, place_verdict, query_params

S = Path(__file__).resolve().parent.parent / "samples"
P1 = json.loads((S / "tix_eventos_p1.json").read_text(encoding="utf-8"))
P2 = json.loads((S / "tix_eventos_p2.json").read_text(encoding="utf-8"))
TODAY = date(2026, 10, 7)


def by_slug(page, today=TODAY):
    return {e.url.rsplit("/", 1)[1]: e for e in (parse_item(it, today) for it in page["data"]) if e}


def item(**attrs):
    base = {"name": "Concierto", "slug": "Concierto-1", "start_at": "2026-10-20T00:30:00.000Z",
            "end_at": "2026-10-20T03:00:00.000Z", "free": False, "place": "Casa de Teatro", "description": ""}
    base.update(attrs)
    return {"id": 1, "attributes": base}


# --- datos reales verificados a mano ---


def test_sandy_gabriel_matches_jazz_en_dominicana():
    e = by_slug(P1)["SANDYGABRIELSJAZZRESIDENCEATTHEGREENROOM-1"]
    assert e.dates == ["2026-10-08"] and e.start_time == "21:30"  # jueves 8, 9:30 p. m.
    assert e.venue == "The Green Room" and e.zone == "Piantini" and not e.needs_review
    assert e.url == e.ticket_url == "https://tix.do/event/SANDYGABRIELSJAZZRESIDENCEATTHEGREENROOM-1"
    assert (e.is_free, e.price_min) == (False, None)  # de pago; el monto no viene en esta API


def test_teatro_joven_weekend_is_a_range_without_time():
    e = by_slug(P1)["FestivaldeTeatroJoven-2"]
    assert e.dates == ["2026-10-09", "2026-10-11"] and e.start_time is None
    assert e.zone == "Ciudad Colonial"


def test_long_residency_starts_today_and_has_no_time():
    e = by_slug(P1)["Pavel-19"]
    assert e.dates == ["2026-10-07", "2026-12-23"] and e.start_time is None  # 3:10 p. m. era la hora de la venta


def test_real_pages_have_no_organizer_data():
    raw = json.dumps(P1) + json.dumps(P2)
    assert "vendor_account" not in raw and "gmail" not in raw


def test_category_from_the_api():
    cats = {e.category for e in by_slug(P2).values()}
    assert "Música" in cats and "Teatro" in cats


# --- reglas ---


def test_other_cities_and_virtual_are_dropped():
    assert parse_item(item(place="Gran Teatro Del Cibao"), TODAY) is None
    assert parse_item(item(place="Centro León"), TODAY) is None
    assert parse_item(item(place="Centro Cultural Eduardo León Jimenes"), TODAY) is None
    assert parse_item(item(place="ONLINE"), TODAY) is None


def test_unknown_venue_is_marked():
    e = parse_item(item(place="Fiesta Alto Nivel"), TODAY)
    assert e.needs_review and place_verdict("Fiesta Alto Nivel") == "desconocido"
    assert place_verdict("Local 3 : Calle Max. Herriquez Ureña 33") == "sdq"  # con la errata de la fuente


def test_map_link_instead_of_venue_is_unknown():
    e = parse_item(item(place="https://maps.app.goo.gl/yHVhV1"), TODAY)
    assert e.venue == "" and e.needs_review


def test_skipped_categories():
    sport = item(event_category={"data": {"id": 9, "attributes": {"name": "🏀 Deporte"}}})
    assert parse_item(sport, TODAY) is None
    music = item(event_category={"data": {"id": 2, "attributes": {"name": "🎵 Música"}}})
    assert parse_item(music, TODAY).category == "Música"


def test_free_and_time_conversion():
    e = parse_item(item(free=True, start_at="2026-10-20T00:30:00.000Z", end_at=None), TODAY)
    assert (e.is_free, e.price_min) == (True, 0)
    assert e.dates == ["2026-10-19"] and e.start_time == "20:30"  # 00:30 UTC = 8:30 p. m. del día anterior


def test_past_and_broken_items_are_dropped():
    assert parse_item(item(start_at="2026-09-01T00:00:00.000Z", end_at="2026-09-01T03:00:00.000Z"), TODAY) is None
    assert parse_item(item(slug=""), TODAY) is None
    assert parse_item(item(start_at="mañana"), TODAY) is None
    assert parse_item({"id": 1}, TODAY) is None


def test_emails_never_reach_the_description():
    e = parse_item(item(description="Info: alguien@gmail.com o al bar"), TODAY)
    assert "@" not in e.description


def test_query_asks_only_for_the_needed_fields():
    params = dict(query_params(datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc), 2))
    assert params["filters[end_at][$gte]"] == "2026-10-07T12:00:00.000Z" and params["pagination[page]"] == "2"
    assert [params[f"fields[{i}]"] for i in range(len(FIELDS))] == FIELDS
    assert not any("vendor" in k or "vendor" in v for k, v in params.items())


# --- la fuente completa ---


def test_run_pages_through_and_publishes_only_known_venues():
    pages = {"1": P1, "2": P2}
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        calls.append(req.url.params.get("pagination[page]"))
        return httpx.Response(200, json=pages[req.url.params["pagination[page]"]])

    logs = []
    f = Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)
    evs = Tix(f, DB(":memory:"), TODAY, "2026-10-07T12:00:00+00:00", log=logs.append).run()
    assert calls == ["1", "2"]
    assert evs and not any(e.needs_review for e in evs)
    assert any("salas por reconocer" in line for line in logs)


def test_registered():
    assert SOURCES["tix"] is Tix
