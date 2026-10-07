"""Pruebas contra páginas reales guardadas en samples/ (5 oct 2026). Se omiten si faltan los archivos."""

from datetime import date
from pathlib import Path

import pytest

from agenda.sources import cce, teatro_nacional, zona_colonial

S = Path(__file__).resolve().parent.parent / "samples"
TODAY = date(2026, 10, 5)


def _read(name):
    p = S / name
    if not p.exists():
        pytest.skip(f"falta {p}")
    return p.read_text(encoding="utf-8")


def test_zona_colonial_real():
    evs = zona_colonial.parse_listing(_read("zonacolonial.html"), zona_colonial.LIST_URL, TODAY)
    assert len(evs) == 11
    by = {e.title[:8]: e for e in evs}
    d = by["El desen"]
    assert d.dates == ["2026-10-06"] and d.start_time == "19:00" and d.is_free is True
    assert d.venue == "Casa de Teatro"
    t = by["TRIBUTO "]
    assert (t.is_free, t.price_min, t.start_time) == (False, 1200, "21:00")
    assert by["RIOZ MUS"].start_time is None
    assert by["VINILO E"].is_free is None  # "Precio $" sin monto


def test_cce_real_cards_filtran_pasados():
    cards = cce.parse_cards(_read("cce_buscador.html"), cce.LIST_URL, TODAY)
    assert len(cards) == 10
    vigentes = [c for c in cards if c["dates"] and max(c["dates"]) >= TODAY.isoformat()]
    assert len(vigentes) == 5
    galeria = next(c for c in cards if c["title"] == "Galería de personajes")
    assert galeria["dates"] == ["2026-10-06", "2026-10-08", "2026-10-09"]
    assert galeria["cats"] == ["Formación"]


def test_teatro_nacional_real():
    e = teatro_nacional.parse_detail(
        _read("teatro_wagner.html"), "https://teatronacional.gob.do/events/wagner-molina/", {}, TODAY
    )
    assert e.title == "Wagner / Molina" and e.dates == ["2026-10-07"]
    assert (e.is_free, e.price_min, e.price_max) == (False, 610, 2290)
    assert e.category == "Música"  # "Categoría: Conciertos"
    assert e.venue.startswith("Sala Carlos Piantini")


def test_casa_de_teatro_api():
    from agenda.sources import casa_de_teatro

    evs = {e.title: e for e in casa_de_teatro.parse_events(_read("casadeteatro_events.json"), TODAY)}
    assert "Evento pasado" not in evs
    j = evs["David Almengod & Marakandé"]
    assert j.dates == ["2026-10-30"] and j.start_time == "20:00"  # 00:00Z = 20:00 en Santo Domingo
    assert (j.category, j.price_min, j.price_max, j.is_free) == ("Música", 1000, 2000, False)
    assert "jazz" in j.tags and j.ticket_url.startswith("https://tix.do/")
    c = evs["Dando Pelo"]
    assert (c.dates, c.start_time, c.category, c.price_min) == (["2026-10-06"], "19:00", "Cine", 200)
    s = evs["Sueño de una noche de verano"]  # dos funciones -> un evento
    assert s.dates == ["2026-10-13", "2026-10-14"] and s.start_time == "20:30"
    t = evs["Taller de lectura"]
    assert t.is_free is True and t.kids is True and "formacion" in t.tags


def test_jazz_en_dominicana_feed():
    """Muestra: Atom con la entrada semanal real (texto visto en la página el 5 oct); el cierre del bloque de
    Retro Jazz se completó a mano porque la lectura se cortó ahí."""
    from agenda.sources import jazz_en_dominicana as j

    entries = j.parse_feed(_read("jazzendominicana_feed.xml"))
    assert len(entries) == 2
    weekly = next(e for e in entries if "Jazz en Vivo" in e["title"])
    from agenda.htmlutil import parse, text_lines

    lines = text_lines(parse(f"<body>{weekly['html']}</body>"))
    evs, skipped = j.parse_weekly(weekly["title"], lines, weekly["published"], weekly["url"], TODAY)
    assert skipped == 2  # Santiago y Sosúa
    by = {e.title.split(" ")[0]: e for e in evs}
    assert len(evs) == 3
    g = by["Sandy"]
    assert (g.title, g.dates, g.start_time, g.venue, g.zone) == (
        "Sandy Gabriel Jazz Residence", ["2026-10-08"], "21:30", "The Green Room", "Piantini")
    assert (g.is_free, g.price_min, g.price_max) == (False, 1500, 2000)  # "No cover" pero boletas a RD$
    f = by["Fiesta"]
    assert f.dates == ["2026-10-09"] and f.start_time == "20:00" and f.venue.startswith("Dominican Fiesta")
    r = by["Retro"]
    assert r.dates == ["2026-10-10"] and r.start_time == "20:30" and r.venue == "Teatro Nacional"
    assert all("jazz" in e.tags and e.category == "Música" for e in evs)


def test_jazz_resolve_date():
    from agenda.sources.jazz_en_dominicana import resolve_date

    assert resolve_date("Jueves", 8, date(2026, 10, 3)) == date(2026, 10, 8)
    assert resolve_date("Sábado", 7, date(2026, 10, 30)) == date(2026, 11, 7)  # cambio de mes
    assert resolve_date("Lunes", 8, date(2026, 10, 3)) is None  # el 8 oct 2026 es jueves, no lunes
