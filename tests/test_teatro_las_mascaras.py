"""Pruebas de Teatro Las Máscaras: HTML sintético para la lógica y la portada real guardada el 6 oct 2026
(samples/teatrolasmascaras.html, solo la cartelera)."""

from datetime import date
from pathlib import Path

from agenda.sources import SOURCES
from agenda.sources.teatro_las_mascaras import TeatroLasMascaras, parse_page

TODAY = date(2026, 10, 6)
BASE = "https://teatrolasmascaras.com/"

PARKING = """<p>🚗 Parqueo en Plaza Colonial:</p><p>2 primeras horas: RD$50</p><p>A partir de la 3ra hora: RD$100</p>
<p>(Descuento al presentar boleta con sello de Redsati)</p>"""
SCHEDULE = "<p>Funciones: Viernes y Sábados 8:30 p.m. | Domingos 6:30 p.m.</p>"


def block(title, dates, tickets="<p>🎟️ Boletas: RD$875 p/p</p><p>Disponibles en Tix.do</p>", href="https://tix.do/event/X-1",
          text="Una propuesta fresca, íntima y cercana pensada para los amantes del buen teatro que buscan planes diferentes."):
    link = f'<a href="{href}">OBTEN TU BOLETA AQUI</a>' if href else ""
    return f"<section><h2>{title}</h2><p>{dates}</p><p>{text}</p>{SCHEDULE}{tickets}{PARKING}{link}</section>"


def page(*blocks, extra=""):
    return (
        "<html><body><nav><a href='/'>Bienvenidos</a><a href='/cartelera/'>CARTELERA</a><a href='/talleres/'>Talleres</a></nav>"
        f"<main>{extra}{''.join(blocks)}</main><footer>Contacto</footer></body></html>"
    )


HTML = page(
    block("Festival Teatro Joven", "Del 2 al 18 de Octubre, 2026", href="https://tix.do/event/FestivaldeTeatroJoven-1"),
    block("Vamos Hacerlo Parados", "Del 23 de Octubre al 1 de Noviembre, 2026", href="https://tix.do/event/VamosaHacerloParados-1"),
    block("Las Locuras de Papi y Mami", "Del 13 al 29 de noviembre", href="https://tix.do/"),
)


def by_title(events):
    return {e.title: e for e in events}


def test_three_productions_with_ranges():
    evs = by_title(parse_page(HTML, BASE, TODAY))
    assert list(evs) == ["Festival Teatro Joven", "Vamos Hacerlo Parados", "Las Locuras de Papi y Mami"]
    assert evs["Festival Teatro Joven"].dates == ["2026-10-02", "2026-10-18"]
    assert evs["Vamos Hacerlo Parados"].dates == ["2026-10-23", "2026-11-01"]  # cruza de mes
    assert evs["Las Locuras de Papi y Mami"].dates == ["2026-11-13", "2026-11-29"]  # sin año


def test_price_is_the_ticket_not_the_parking():
    for e in parse_page(HTML, BASE, TODAY):
        assert (e.is_free, e.price_min, e.price_max) == (False, 875, 875)


def test_time_is_not_invented_when_days_differ():
    e = parse_page(HTML, BASE, TODAY)[0]
    assert e.start_time is None
    assert "Viernes y Sábados 8:30 p.m." in e.description and "Domingos 6:30 p.m." in e.description


def test_single_time_is_kept():
    html = page(block("Obra única", "Del 9 al 11 de octubre, 2026").replace(
        "Funciones: Viernes y Sábados 8:30 p.m. | Domingos 6:30 p.m.", "Funciones: Viernes y Sábados 8:30 p.m."))
    assert parse_page(html, BASE, TODAY)[0].start_time == "20:30"


def test_urls_are_unique_per_production_and_point_to_the_source():
    urls = [e.url for e in parse_page(HTML, BASE, TODAY)]
    assert len(set(urls)) == 3
    assert urls[0] == "https://teatrolasmascaras.com/#festival-teatro-joven"


def test_keys_differ_between_productions():
    assert len({e.key for e in parse_page(HTML, BASE, TODAY)}) == 3


def test_ticket_links_and_generic_tix_home_is_dropped():
    evs = parse_page(HTML, BASE, TODAY)
    assert evs[0].ticket_url == "https://tix.do/event/FestivaldeTeatroJoven-1"
    assert evs[1].ticket_url == "https://tix.do/event/VamosaHacerloParados-1"
    assert evs[2].ticket_url == ""  # "https://tix.do/" no lleva a la función


def test_ticket_links_come_from_each_block_and_never_cross():
    html = page(block("Obra A", "Del 9 al 11 de octubre, 2026", href=None),
                block("Obra B", "Del 16 al 18 de octubre, 2026", href="https://tix.do/event/B-1"))
    assert [e.ticket_url for e in parse_page(html, BASE, TODAY)] == ["", "https://tix.do/event/B-1"]


def test_real_markup_quirks():
    """Como la portada real: fechas entre asteriscos y "Boletas:" en <strong> con el monto en el mismo párrafo."""
    html = (
        '<div class="entry-content"><h2>Obra real</h2><p>**Del 9 al 11 de octubre, 2026**</p>'
        '<figure><img src="x.jpg"></figure><p>Funciones: Viernes 8:30 p.m.</p>'
        '<p>🎟️ <strong>Boletas:</strong> RD$600 p/p<br>Disponibles en <a href="https://tix.do/event/Real-1">Tix.do</a></p>'
        '<p>🚗 <strong>Parqueo:</strong><br>2 primeras horas: RD$50</p></div>'
    )
    e = parse_page(html, BASE, TODAY)[0]
    assert e.dates == ["2026-10-09", "2026-10-11"] and e.price_min == 600 and e.start_time == "20:30"
    assert e.ticket_url == "https://tix.do/event/Real-1"


REAL = Path(__file__).resolve().parent.parent / "samples" / "teatrolasmascaras.html"


def test_real_page():
    evs = parse_page(REAL.read_text(encoding="utf-8"), BASE, TODAY)
    assert [e.title for e in evs] == ["Festival Teatro Joven", "Vamos Hacerlo Parados", "Las Locuras de Papi y Mami"]
    assert [e.dates for e in evs] == [["2026-10-02", "2026-10-18"], ["2026-10-23", "2026-11-01"], ["2026-11-13", "2026-11-29"]]
    assert all((e.is_free, e.price_min) == (False, 875) for e in evs)  # nunca el parqueo (RD$50 / RD$100)
    assert all(e.start_time is None and "Domingos 6:30 p.m." in e.description for e in evs)
    assert [e.ticket_url for e in evs] == [
        "https://tix.do/event/FestivaldeTeatroJoven-1", "https://tix.do/event/VamosaHacerloParados-1", ""]
    assert evs[0].description.startswith("Funciones:") and len(evs[0].description) <= 280


def test_category_venue_zone_and_kids():
    e = parse_page(HTML, BASE, TODAY)[0]
    assert (e.category, e.venue, e.zone, e.kids) == ("Teatro", "Teatro Las Máscaras", "Ciudad Colonial", False)
    kids = parse_page(page(block("Teatro para niños", "Del 9 al 11 de octubre, 2026")), BASE, TODAY)[0]
    assert kids.kids is True


def test_past_productions_are_dropped_and_current_ones_kept():
    html = page(block("Vieja", "Del 2 al 4 de mayo, 2026"), block("En curso", "Del 2 al 18 de octubre, 2026"))
    assert [e.title for e in parse_page(html, BASE, TODAY)] == ["En curso"]


def test_missing_price_is_unconfirmed_never_free():
    html = page(block("Sin precio", "Del 9 al 11 de octubre, 2026", tickets="<p>Boletas disponibles en Tix.do</p>"))
    e = parse_page(html, BASE, TODAY)[0]
    assert (e.is_free, e.price_min, e.price_max) == (None, None, None)


def test_free_entry_is_free_only_if_stated():
    html = page(block("Con entrada libre", "Del 9 al 11 de octubre, 2026", tickets="<p>Entradas: Entrada libre</p>"))
    e = parse_page(html, BASE, TODAY)[0]
    assert e.is_free is True


def test_single_day_gets_one_date():
    html = page(block("Una función", "Del 9 de octubre de 2026"))
    assert parse_page(html, BASE, TODAY)[0].dates == ["2026-10-09"]


def test_description_is_short():
    html = page(block("Larga", "Del 9 al 11 de octubre, 2026", text="x " * 400))
    assert len(parse_page(html, BASE, TODAY)[0].description) <= 280


def test_menu_and_footer_are_not_productions():
    html = page(block("Obra", "Del 9 al 11 de octubre, 2026"))
    assert [e.title for e in parse_page(html, BASE, TODAY)] == ["Obra"]


def test_page_without_productions_gives_empty_list():
    assert parse_page(page(), BASE, TODAY) == []
    assert parse_page("<html><body></body></html>", BASE, TODAY) == []


def test_registered_source():
    assert SOURCES["teatro_las_mascaras"] is TeatroLasMascaras
