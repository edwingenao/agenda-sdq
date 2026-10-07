"""Pruebas de las series recurrentes (Domingos de Bonyé y similares)."""

import json
from datetime import date

import pytest

from agenda.db import DB
from agenda.export import export_json
from agenda.sources import recurring

TODAY = date(2026, 10, 6)  # martes

BASE = {
    "id": "s1",
    "title": "Serie de prueba",
    "pattern": {"freq": "weekly", "weekday": "domingo"},
    "start_time": "18:00",
    "end_time": "22:00",
    "venue": "Un lugar",
    "category": ["Música"],
    "price": {"status": "free"},
    "sources": [{"name": "x", "url": "https://example.com/x"}],
    "confidence": "listado",
    "last_confirmed": "2026-10-06",
}


def raw(**over):
    return {**BASE, **over}


def run(*entries, today=TODAY, **kw):
    return recurring.collect({"series": list(entries)}, today=today, **kw)


def days(res):
    return [date.fromisoformat(e.start) for e in res.events]


def of(res, series_id):
    return [e for e in res.events if f"#{series_id}-" in e.url]


# --- semanal ---


def test_today_is_a_tuesday():
    assert TODAY.weekday() == 1


def test_weekly_sundays_in_window():
    res = run(raw())
    assert days(res) == [date(2026, 10, 11), date(2026, 10, 18), date(2026, 10, 25), date(2026, 11, 1)]


def test_today_is_included_when_it_matches():
    res = run(raw(), today=date(2026, 10, 11), horizon_days=0)
    assert days(res) == [date(2026, 10, 11)]


def test_window_end_is_inclusive():
    assert days(run(raw(), horizon_days=5)) == [date(2026, 10, 11)]  # domingo, 5 días después
    res = run(raw(), horizon_days=4)
    assert res.events == [] and res.empty == ["s1"]


def test_multiple_weekdays_accept_accents():
    res = run(raw(pattern={"freq": "weekly", "weekday": ["sábado", "Domingo"]}), horizon_days=6)
    assert days(res) == [date(2026, 10, 10), date(2026, 10, 11)]


def test_exceptions_are_skipped():
    res = run(raw(exceptions=["2026-10-18"]))
    assert date(2026, 10, 18) not in days(res) and len(res.events) == 3


def test_validity_range_is_respected():
    res = run(raw(valid_from="2026-10-15", valid_until="2026-10-25"))
    assert days(res) == [date(2026, 10, 18), date(2026, 10, 25)]


# --- mensual ---


def test_first_saturday_of_month():
    res = run(raw(pattern={"freq": "monthly_nth", "weekday": "sábado", "nth": 1}), horizon_days=60)
    assert days(res) == [date(2026, 11, 7), date(2026, 12, 5)]


def test_last_saturday_of_month():
    res = run(raw(pattern={"freq": "monthly_nth", "weekday": "sábado", "nth": -1}), horizon_days=60)
    assert days(res) == [date(2026, 10, 31), date(2026, 11, 28)]


def test_second_sunday_of_month():
    res = run(raw(pattern={"freq": "monthly_nth", "weekday": "domingo", "nth": 2}), horizon_days=40)
    assert days(res) == [date(2026, 10, 11), date(2026, 11, 8)]


# --- fechas sueltas ---


def test_explicit_dates():
    res = run(raw(pattern={"freq": "dates", "dates": ["2026-11-15", "2026-11-14"]}), horizon_days=60)
    assert days(res) == [date(2026, 11, 14), date(2026, 11, 15)]


def test_explicit_dates_ignore_the_window():
    res = run(raw(pattern={"freq": "dates", "dates": ["2026-12-20"]}), horizon_days=7)
    assert days(res) == [date(2026, 12, 20)] and res.empty == []


def test_past_explicit_dates_are_empty():
    res = run(raw(pattern={"freq": "dates", "dates": ["2026-09-01"]}))
    assert res.events == [] and res.empty == ["s1"]


# --- hora ---


def test_time_is_kept():
    ev = run(raw()).events[0]
    assert ev.dates == ["2026-10-11"] and ev.start_time == "18:00"


def test_end_past_midnight_is_accepted():
    assert run(raw(start_time="22:00", end_time="02:00")).events[0].start_time == "22:00"


def test_missing_time_is_not_invented():
    ev = run(raw(start_time=None, end_time=None)).events[0]
    assert ev.start_time is None and ev.to_public()["time"] == ""


# --- precio ---


def test_free():
    ev = run(raw()).events[0]
    assert ev.is_free is True and ev.price_min == 0 and ev.to_public()["price"] == 0


def test_paid_with_range():
    ev = run(raw(price={"status": "paid", "min": 200, "max": "500"})).events[0]
    assert ev.is_free is False and (ev.price_min, ev.price_max) == (200, 500)


def test_paid_single_amount_has_no_max():
    ev = run(raw(price={"status": "paid", "min": 300})).events[0]
    assert (ev.price_min, ev.price_max) == (300, None)


def test_paid_without_amounts_is_paid_but_price_unknown():
    ev = run(raw(price={"status": "paid"})).events[0]
    assert ev.is_free is False and ev.price_min is None and ev.price_max is None


@pytest.mark.parametrize("price", [{"status": "unconfirmed"}, {}, None])
def test_unconfirmed_price_is_never_free(price):
    ev = run(raw(price=price)).events[0]
    assert ev.is_free is None and ev.price_min is None and ev.to_public()["price"] is None


def test_missing_price_key_is_unconfirmed():
    entry = raw()
    del entry["price"]
    assert run(entry).events[0].is_free is None


# --- campos y modelo real ---


def test_basic_fields():
    ev = run(raw(description="Texto")).events[0]
    assert ev.source == "recurring" and ev.source_name == "x"
    assert ev.url == "https://example.com/x#s1-2026-10-11"
    assert ev.category == "Música" and ev.venue == "Un lugar" and ev.description == "Texto"
    assert "serie" in ev.tags and not ev.needs_review


def test_second_category_goes_to_tags():
    ev = run(raw(category=["Música", "Cultura"])).events[0]
    assert ev.category == "Música" and "cultura" in ev.tags


def test_each_date_has_its_own_key():
    evs = run(raw(), horizon_days=60).events
    assert len({e.key for e in evs}) == len(evs)


def test_url_falls_back_to_first_source():
    assert run(raw()).events[0].url.startswith("https://example.com/x#")
    assert run(raw(url="https://example.com/oficial")).events[0].url.startswith("https://example.com/oficial#")


def test_zone_from_venue():
    assert run(raw(venue="Ruinas de San Francisco, Zona Colonial")).events[0].zone == "Ciudad Colonial"


def test_events_sorted_by_start_across_series():
    a = raw(id="a", start_time="20:00")
    b = raw(id="b", start_time="09:00")
    starts = [(e.start, e.start_time) for e in run(a, b).events]
    assert starts == sorted(starts)


# --- activas / temporada ---


def test_inactive_series_do_not_generate_and_are_reported():
    res = run(raw(active=False))
    assert res.events == [] and res.skipped_inactive == ["s1"] and res.loaded == 1


def test_inactive_can_be_previewed():
    res = run(raw(active=False), include_inactive=True)
    assert len(res.events) == 4 and res.skipped_inactive == []


def test_active_series_past_its_season_is_reported_as_empty():
    res = run(raw(valid_until="2026-07-30"))
    assert res.events == [] and res.empty == ["s1"]


# --- confirmación ---


def test_not_stale_on_the_last_day():
    res = run(raw(stale_after_days=60), today=date(2026, 12, 5))
    assert res.stale == [] and all(not e.needs_review for e in res.events)


def test_stale_the_day_after():
    res = run(raw(stale_after_days=60), today=date(2026, 12, 6))
    assert res.stale == ["s1"] and all(e.needs_review and "confirmar" in e.tags for e in res.events)
    assert res.events  # se sigue mostrando


def test_never_confirmed_is_stale():
    res = run(raw(last_confirmed=None))
    assert res.stale == ["s1"] and res.events[0].needs_review is True


def test_unverified_needs_confirmation_even_if_recent():
    res = run(raw(confidence="sin_verificar"))
    assert res.events[0].needs_review is True and res.stale == []


# --- robustez ---


@pytest.mark.parametrize("over", [
    {"pattern": {"freq": "weekly", "weekday": "funday"}},
    {"pattern": {"freq": "weekly"}},
    {"pattern": {"freq": "daily"}},
    {"pattern": {"freq": "monthly_nth", "weekday": "sábado", "nth": 5}},
    {"pattern": {"freq": "monthly_nth", "weekday": "sábado", "nth": True}},
    {"pattern": {"freq": "monthly_nth", "weekday": ["sábado", "domingo"], "nth": 1}},
    {"pattern": {"freq": "dates", "dates": []}},
    {"pattern": {"freq": "dates", "dates": ["no-es-fecha"]}},
    {"start_time": "25:00"},
    {"start_time": "6pm"},
    {"start_time": None, "end_time": "22:00"},
    {"category": ["Música", "Cultura", "Gastronomía"]},
    {"category": ["Deportes"]},
    {"category": []},
    {"sources": []},
    {"sources": None},
    {"valid_from": "2026-11-01", "valid_until": "2026-10-01"},
    {"price": {"status": "paid", "min": 500, "max": 200}},
    {"price": {"status": "gratis"}},
    {"price": {"status": "paid", "min": -5}},
    {"confidence": "seguro"},
    {"stale_after_days": 0},
    {"active": "si"},
    {"title": "  "},
    {"exceptions": "2026-10-18"},
])
def test_invalid_series_raise(over):
    with pytest.raises(ValueError):
        recurring.parse_series(raw(**over))


def test_invalid_entries_are_skipped_and_reported_not_fatal():
    good = raw(id="bien")
    bad_day = raw(id="mal-dia", pattern={"freq": "weekly", "weekday": "funday"})
    no_id = {k: v for k, v in raw().items() if k != "id"}
    dup = raw(id="bien")
    res = run(good, bad_day, no_id, dup, "basura")
    assert len(of(res, "bien")) == 4 and len(res.events) == 4
    assert res.loaded == 1 and len(res.skipped_invalid) == 4
    assert any("mal-dia" in s for s in res.skipped_invalid)
    assert any("id repetido" in s for s in res.skipped_invalid)


@pytest.mark.parametrize("bad", [{}, {"series": "x"}, {"series": {"a": 1}}, [], None])
def test_unreadable_structure_raises(bad):
    with pytest.raises(ValueError):
        recurring.collect(bad, today=TODAY)


# --- el archivo que se entrega ---

SHIPPED = dict(source=recurring.DEFAULT_PATH, today=TODAY, horizon_days=60)


def test_shipped_file_has_no_invalid_entries():
    res = recurring.collect(**SHIPPED)
    assert res.skipped_invalid == []
    assert res.loaded >= 6


def test_shipped_bonye_is_the_next_sunday():
    bonye = of(recurring.collect(**SHIPPED), "bonye-domingos")
    first = bonye[0]
    assert first.dates == ["2026-10-11"] and first.start_time == "18:00"
    assert first.is_free is True and first.category == "Música" and "cultura" in first.tags
    assert "San Francisco" in first.venue and first.zone == "Ciudad Colonial"
    assert first.needs_review is False
    # 11 oct al 29 nov (la ventana de 60 días termina el 5 dic)
    assert all(date.fromisoformat(e.start).weekday() == 6 for e in bonye) and len(bonye) == 8


def test_shipped_bonye_asks_for_confirmation_when_old():
    res = recurring.collect(source=recurring.DEFAULT_PATH, today=date(2027, 1, 15), horizon_days=7)
    assert "bonye-domingos" in res.stale
    assert all(e.needs_review for e in of(res, "bonye-domingos"))


def test_shipped_809_mercado_is_loaded_without_inventing_time_or_price():
    mercado = of(recurring.collect(**SHIPPED), "809-mercado-2026-11")
    assert [e.start for e in mercado] == ["2026-11-14", "2026-11-15"]
    assert all(e.start_time is None and e.is_free is None for e in mercado)
    assert mercado[0].category == "Gastronomía" and "cultura" in mercado[0].tags


def test_shipped_eurocine_is_a_week_of_cinema_without_invented_time_or_price():
    eurocine = of(recurring.collect(**SHIPPED), "eurocine-2026")
    assert [e.start for e in eurocine] == [f"2026-10-{d}" for d in range(26, 32)] + ["2026-11-01"]
    assert all(e.category == "Cine" and e.start_time is None and e.is_free is None for e in eurocine)
    assert eurocine[0].source_name == "DGCINE" and not eurocine[0].needs_review


def test_shipped_seasonal_and_unverified_series_stay_off():
    res = recurring.collect(**SHIPPED)
    off = {
        "cine-dominicano-banreservas", "cine-dominicano-casa-de-teatro",
        "turizoneando-folclor-sabados", "plaza-de-la-cultura-fines-de-semana",
    }
    assert off <= set(res.skipped_inactive)
    assert not any(of(res, sid) for sid in off)


def test_shipped_nothing_active_is_forgotten_past_its_season():
    # Una serie activa cuya temporada ya terminó aparece en `empty`: aquí no debe haber ninguna.
    assert recurring.collect(**SHIPPED).empty == []


def test_shipped_ids_are_unique():
    with open(recurring.DEFAULT_PATH, encoding="utf-8") as fh:
        ids = [s["id"] for s in json.load(fh)["series"]]
    assert len(ids) == len(set(ids))


# --- como fuente de la corrida, hasta events.json ---


def test_source_run_and_export(tmp_path):
    db = DB(":memory:")
    logs = []
    evs = recurring.SeriesRecurrentes(None, db, TODAY, "2026-10-06T12:00:00+00:00", log=logs.append).run()
    assert len(evs) == 14  # 4 domingos de Bonyé en 28 días + 7 días de EUROCINE + 2 de 809 Mercado + la inauguración de Gerard Ellis
    assert any("8 series" in line for line in logs)
    for e in evs:
        assert db.upsert_event(e, "2026-10-06T12:00:00+00:00") == "new"
    out = tmp_path / "events.json"
    assert export_json(db, out, TODAY) == 14
    pub = json.loads(out.read_text(encoding="utf-8"))["events"]
    assert pub[0]["title"] == "Domingos de Bonyé" and pub[0]["time"] == "18:00" and pub[0]["price"] == 0
    assert pub[0]["srcName"] == "SalsaVida" and pub[0]["zone"] == "Ciudad Colonial"
    assert [p["cat"] for p in pub if p["title"] == "809 Mercado"] == ["Gastronomía", "Gastronomía"]


def test_shipped_gerard_ellis_inauguration():
    ev = next(e for e in recurring.events(today=TODAY, horizon_days=14) if e.title.startswith("Gerard Ellis"))
    assert ev.dates == ["2026-10-15"] and ev.start_time == "19:00"
    assert ev.category == "Arte" and ev.zone == "Piantini"
    assert ev.is_free is True  # el flyer no trae precio; la gratuidad la confirmó Edwin el 7 de octubre
