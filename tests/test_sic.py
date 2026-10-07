"""SIC-RD con las dos páginas reales de la API guardadas el 6 oct 2026 (samples/sic_events_p*.json)."""

import json
from datetime import date
from pathlib import Path

import httpx

from agenda.db import DB
from agenda.http import Fetcher
from agenda.sources.sic import MinisterioCulturaSIC, parse_events

S = Path(__file__).resolve().parent.parent / "samples"
P1 = json.loads((S / "sic_events_p1.json").read_text(encoding="utf-8"))
P2 = json.loads((S / "sic_events_p2.json").read_text(encoding="utf-8"))
ALL = {"data": P1["data"] + P2["data"]}
NOW = "2026-10-06T12:00:00+00:00"


def by_id(evs):
    return {int(e.url.rsplit("/", 1)[1]): e for e in evs}


def test_solo_eventos_desde_hoy():
    evs = parse_events(ALL, date(2026, 9, 29))
    assert sorted(e.start for e in evs) == ["2026-09-29"] * 3 + ["2026-09-30", "2026-10-01", "2026-10-04"]


def test_sin_eventos_futuros_el_dia_de_la_muestra():
    assert parse_events(ALL, date(2026, 10, 6)) == []


def test_campos_de_un_evento():
    e = by_id(parse_events(ALL, date(2026, 9, 29)))[30]
    assert e.title == "Maratón de Lectura - Círculo Literario EscribasRD"
    assert e.dates == ["2026-10-04"]  # la API manda medianoche UTC: se toma como fecha sin hora
    assert e.start_time == "10:00"
    assert (e.is_free, e.price_min) == (True, 0)
    assert e.venue == "Teatro Nacional - Sala Aída Bonelly de Díaz"
    assert e.zone == "Plaza de la Cultura"
    assert e.url == "https://sic.cultura.gob.do/agenda/evento/30"
    assert e.category == "Cultura" and not e.needs_review


def test_une_el_repetido_de_la_api():
    evs = by_id(parse_events(ALL, date(2026, 9, 29)))
    assert 27 in evs and 29 not in evs  # 29 es la misma conferencia cargada otra vez


def test_filtra_fuera_de_santo_domingo_e_invitacion_cerrada():
    ids = by_id(parse_events(ALL, date(2026, 1, 1)))
    assert 23 not in ids  # Festival del Este, Higüey
    assert 10 not in ids  # San Cristóbal, invitación cerrada
    assert len(ids) == 17  # 20 - Higüey - San Cristóbal - repetido


def test_sin_municipio_queda_para_revisar():
    e = by_id(parse_events(ALL, date(2026, 1, 1)))[14]  # Galería Ramón Oviedo, sin municipio
    assert e.needs_review


def test_taller_en_el_teatro_no_cae_en_teatro():
    e = by_id(parse_events(ALL, date(2026, 9, 29)))[26]  # Taller "..." en el Teatro Nacional
    assert e.category == "Cultura" and "formacion" in e.tags


def test_run_pide_desde_hoy_y_recorre_las_paginas():
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        calls.append(dict(req.url.params))
        page = int(req.url.params.get("page", 1))
        return httpx.Response(200, json=P1 if page == 1 else P2)

    f = Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)
    evs = MinisterioCulturaSIC(f, DB(":memory:"), date(2026, 9, 29), NOW, log=lambda *_: None).run()
    assert calls == [{"date_from": "2026-09-29", "page": "1"}, {"date_from": "2026-09-29", "page": "2"}]
    assert len(evs) == 6
