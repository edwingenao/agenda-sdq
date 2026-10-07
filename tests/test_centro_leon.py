"""Centro León: casos sintéticos + la respuesta real del 6 oct 2026 (samples/centroleon_events.json)."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from agenda.db import DB
from agenda.http import Fetcher
from agenda.sources import centro_leon as cl

TODAY = date(2026, 10, 6)
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "centroleon_events.json"

SD_VENUE = {"venue": "Centro León Extensión", "address": "Calle Las Damas no. 42,", "city": "Santo Domingo"}
SANTIAGO = {"venue": "Centro León", "address": "Avenida 27 de Febrero no. 146,", "city": "Santiago de los Caballeros"}


def raw(**over):
    base = {
        "id": 1,
        "status": "publish",
        "title": "CONVERSATORIO",
        "url": "https://centroleon.org.do/actividad/conversatorio-11/",
        "description": "<p>Encuentro con <b>escritor</b> &amp; invitado</p>",
        "all_day": False,
        "start_date": "2026-10-07 19:00:00",
        "end_date": "2026-10-07 21:00:00",
        "timezone": "America/Santo_Domingo",
        "cost": "",
        "hide_from_listings": False,
        "venue": SD_VENUE,
        "categories": [{"name": "Conversatorios"}, {"name": "Programa de actividades"}],
    }
    base.update(over)
    return base


def pages(*page_events):
    """get_json falso: la página i devuelve sus eventos y apunta a la siguiente."""
    urls = [f"page{i}" for i in range(len(page_events))]
    seen = []

    def get_json(url):
        seen.append(url)
        i = urls.index(url) if url in urls else 0
        return {"events": page_events[i], "next_rest_url": urls[i + 1] if i + 1 < len(urls) else None}

    get_json.seen = seen
    return get_json


def run(*evs, **kw):
    return cl.collect(pages(list(evs)), TODAY, **kw)


# --- campos básicos ---


def test_basic_event():
    ev = run(raw()).events[0]
    assert ev.title == "CONVERSATORIO" and ev.source == "centro_leon"
    assert ev.dates == ["2026-10-07"] and ev.start_time == "19:00"
    assert ev.url.endswith("conversatorio-11/")
    assert ev.venue == "Centro León Extensión, Santo Domingo"
    assert ev.zone == "Ciudad Colonial"


def test_description_is_plain_text():
    assert run(raw()).events[0].description == "Encuentro con escritor & invitado"


def test_long_description_is_truncated():
    ev = run(raw(description="x " * 600)).events[0]
    assert len(ev.description) <= cl.MAX_DESCRIPTION and ev.description.endswith("…")


def test_local_time_is_not_converted():
    assert run(raw(utc_start_date="2026-10-07 23:00:00")).events[0].start_time == "19:00"


def test_all_day_has_no_invented_time():
    ev = run(raw(all_day=True, start_date="2026-10-10 00:00:00", end_date="2026-10-10 23:59:59")).events[0]
    assert ev.start_time is None and ev.dates == ["2026-10-10"]


def test_multi_day_range_keeps_end():
    ev = run(raw(start_date="2026-10-10 14:00:00", end_date="2026-10-31 18:00:00")).events[0]
    assert ev.dates == ["2026-10-10", "2026-10-31"] and ev.to_public()["end"] == "2026-10-31"


def test_end_before_start_is_dropped():
    assert run(raw(end_date="2026-10-06 18:00:00")).events[0].dates == ["2026-10-07"]


def test_missing_end_is_ok():
    assert run(raw(end_date="")).events[0].dates == ["2026-10-07"]


# --- precio ---


@pytest.mark.parametrize("cost", ["", None, "   ", "Consultar", "Por confirmar"])
def test_empty_or_unclear_cost_is_never_free(cost):
    ev = run(raw(cost=cost)).events[0]
    assert ev.is_free is None and ev.price_min is None and ev.price_max is None


@pytest.mark.parametrize("cost", ["Gratis", "Entrada libre", "gratuita", "0", "RD$ 0"])
def test_free_costs(cost):
    ev = run(raw(cost=cost)).events[0]
    assert ev.is_free is True and ev.price_min == 0 and ev.to_public()["price"] == 0


def test_paid_cost_with_amount():
    ev = run(raw(cost="RD$ 500")).events[0]
    assert ev.is_free is False and ev.price_min == 500 and ev.price_max is None


def test_paid_cost_with_range_and_thousands():
    ev = run(raw(cost="RD$ 1,500 - 2,500")).events[0]
    assert (ev.price_min, ev.price_max) == (1500, 2500)


# --- categorías (las del repo: Música, Teatro, Danza, Arte, Cine, Cultura) ---


@pytest.mark.parametrize(
    "cats,title,expected",
    [
        ([{"name": "Viernes Musicales"}], "VIERNES MUSICALES / CAFÉ BOHEMIO", "Música"),
        ([{"name": "Cine Club"}], "CINE CLUB / ANIVERSARIO", "Cine"),
        ([{"name": "Proyección Documental"}], "PROYECCIÓN DOCUMENTAL", "Cine"),
        ([{"name": "Educación"}], "TALLER DE GRABADO", "Cultura"),
        ([{"name": "Encuentro"}], "RECORRIDO POR ESPECIALISTAS", "Cultura"),
        ([], "Algo sin categoría", "Cultura"),
    ],
)
def test_categories(cats, title, expected):
    assert run(raw(categories=cats, title=title)).events[0].category == expected


def test_taller_is_tagged_formacion():
    assert "formacion" in run(raw(title="TALLER DE GRABADO")).events[0].tags


# --- filtro de lugar ---


def test_santiago_events_are_skipped_and_counted():
    res = run(raw(id=1), raw(id=2, venue=SANTIAGO))
    assert len(res.events) == 1 and res.skipped_other_place == 1 and res.fetched == 2


@pytest.mark.parametrize(
    "city,address,expected",
    [
        ("Santo Domingo", "", True),
        ("Distrito Nacional", "", True),
        ("Santo Domingo de Guzmán", "", True),
        ("santo domingo", "", True),
        ("Santiago de los Caballeros", "", False),
        ("Salcedo", "", False),
        ("", "Calle Las Damas 42", True),
        ("", "", False),
        ("Santo Domingo Este", "", False),
    ],
)
def test_is_santo_domingo(city, address, expected):
    assert cl.is_santo_domingo(city, address) is expected


def test_event_without_venue_is_not_published():
    res = run(raw(id=3, venue=[]))
    assert res.events == [] and res.skipped_other_place == 1


# --- ocultos y rotos ---


def test_hidden_and_unpublished_are_skipped_silently():
    res = run(raw(id=1, hide_from_listings=True), raw(id=2, status="draft"))
    assert res.events == [] and res.skipped_invalid == []


def test_broken_events_are_reported_not_fatal():
    res = run(raw(id=1), raw(id=2, title="  "), raw(id=3, start_date="mañana"), "basura")
    assert len(res.events) == 1 and len(res.skipped_invalid) == 3
    assert any("evento 2" in s for s in res.skipped_invalid)


def test_duplicate_ids_are_published_once():
    assert len(run(raw(id=1), raw(id=1)).events) == 1


def test_sorted_by_start():
    res = run(raw(id=1, start_date="2026-10-20 19:00:00", end_date=""),
              raw(id=2, start_date="2026-10-08 19:00:00", end_date=""))
    assert [e.start for e in res.events] == ["2026-10-08", "2026-10-20"]


# --- paginación ---


def test_follows_next_page():
    get_json = pages([raw(id=1)], [raw(id=2)], [raw(id=3)])
    res = cl.collect(get_json, TODAY)
    assert res.pages == 3 and len(res.events) == 3
    assert "start_date=2026-10-06" in get_json.seen[0] and "per_page=50" in get_json.seen[0]


def test_max_pages_stops_runaway_pagination():
    assert cl.collect(lambda u: {"events": [], "next_rest_url": "otra"}, TODAY, max_pages=3).pages == 3


def test_first_page_failure_is_loud():
    def boom(url):
        raise OSError("sin red")

    with pytest.raises(OSError):
        cl.collect(boom, TODAY)


def test_first_page_without_events_list_is_loud():
    with pytest.raises(ValueError):
        cl.collect(lambda u: {"error": "x"}, TODAY)


def test_later_page_failure_keeps_what_was_read():
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"events": [raw(id=1)], "next_rest_url": "p2"}
        raise OSError("corte")

    res = cl.collect(flaky, TODAY)
    assert len(res.events) == 1 and any("página 2" in s for s in res.skipped_invalid)


def test_empty_agenda_is_not_an_error():
    res = run()
    assert res.events == [] and res.pages == 1


# --- respuesta real y corrida con el cliente HTTP ---


def test_real_sample_is_all_santiago():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    res = cl.collect(lambda u: data, TODAY)
    assert res.fetched == 19 and res.skipped_other_place == 19 and res.events == []
    assert res.skipped_invalid == []
    # Si esos eventos fueran en Santo Domingo, todos se leerían bien:
    for e in data["events"]:
        e["venue"] = SD_VENUE
    assert len(cl.collect(lambda u: data, TODAY).events) == 19


def test_run_uses_polite_fetcher():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /wp-content/uploads/wpforms/\n")
        return httpx.Response(200, json={"events": [raw()], "next_rest_url": None})

    f = Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)
    logs = []
    evs = cl.CentroLeon(f, DB(":memory:"), TODAY, "2026-10-06T12:00:00+00:00", log=logs.append).run()
    assert len(evs) == 1 and any("1 en Santo Domingo" in line for line in logs)
