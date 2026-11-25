from datetime import date

from agenda.dedupe import dedupe
from agenda.models import Event
from agenda.sources.zona_colonial import clean_venue, parse_listing

TODAY = date(2026, 11, 24)


def card(title, month, day, price, venue=None, time="20:00", slug=None, day_end=None):
    """Tarjeta como la de zonacolonial.do/actividades (24 nov 2026): mes y día en líneas aparte."""
    slug = slug or title.lower().replace(" ", "-")
    when = f"{day}-{day_end}" if day_end else f"{day}"
    iso = f"2026-{11:02d}-{day:02d}"
    lugar = f"<p>{venue}</p>" if venue else ""
    return f"""<div class="ehm-event-card" data-date="{iso}">
      <a href="https://zonacolonial.do/actividad/{slug}/"><img src="x.jpg"></a>
      <div><span>{month}</span><span>{when}</span></div>
      <h3><a href="https://zonacolonial.do/actividad/{slug}/">{title}</a></h3>
      <div><span>PRECIO</span><span>{price}</span></div>
      {lugar}
      <button data-date="{iso}" data-title="{title}" data-time="{time}">Agendar</button>
      <a href="https://maps.example/x">Ver Mapa</a>
    </div>"""


def listing(*cards):
    return "<html><body><main>" + "".join(cards) + "</main></body></html>"


def parse(*cards):
    return parse_listing(listing(*cards), "https://zonacolonial.do/actividades/", TODAY)


def test_unknown_venue_is_read_not_the_month_label():
    ev = parse(card("HERMINIA EN LA GRUTA", "NOV", 25, "$200",
                    "Sala de teatro La Gruta (La Gruta de Anacaona Teatro, Zona Colonial, Santo Domingo) • Zona Colonial, Santo Domingo"))[0]
    assert ev.venue == "Sala de teatro La Gruta"
    assert ev.start_time == "20:00" and ev.price_min == 200


def test_card_without_venue_leaves_it_empty():
    ev = parse(card("Descubre Santo Domingo Subterraneo", "NOV", 27, "$1300", None, "09:30"))[0]
    assert ev.venue == ""  # nunca "NOV" ni "PRECIO"


def test_day_range_is_published_once_with_end_date():
    ev = parse(card("III Congreso para la Reunificación de la Hispanidad", "NOV", 25, "$", "Biblioteca Nacional", day_end=28))[0]
    assert ev.dates == ["2026-11-25", "2026-11-28"]


def test_clean_venue_keeps_street_addresses_whole():
    assert clean_venue("Calle Arzobispo Meriño #110, Zona Colonial, Santo Domingo. • Zona Colonial, Santo Domingo").startswith("Calle Arzobispo")
    assert clean_venue("Museo del Ámbar, Ciudad Colonial, Santo Domingo • Zona Colonial, Santo Domingo").startswith("Museo del Ámbar")


def _zc(title, venue, price=1300, time="09:30"):
    return Event(source="zona_colonial", source_name="Zona Colonial", url=f"https://zonacolonial.do/{title}", title=title,
                 dates=["2026-11-27"], start_time=time, venue=venue, price_min=price, price_max=price)


def test_same_tour_with_two_names_is_merged_when_one_card_has_no_venue():
    out = dedupe([_zc("Descubre Santo Domingo Subterraneo", ""),
                  _zc("ALCANTARILLA DE LAS ATARAZANAS REALES", "Museo del Ámbar, Ciudad Colonial, Santo Domingo")])
    assert len(out) == 1


def test_different_paid_events_same_time_with_known_venues_stay_separate():
    a = _zc("Concierto A", "Casa de Teatro", 1000, "20:00")
    b = _zc("Obra B", "Museo del Ámbar", 1000, "20:00")
    assert len(dedupe([a, b])) == 2
    c = _zc("Taller C", "", 1000, "10:00")
    assert len(dedupe([a, c])) == 2  # otra hora
    d = _zc("Cine D", "", 0, "20:00")
    e = _zc("Charla E", "", 0, "20:00")
    assert len(dedupe([d, e])) == 2  # gratis sin lugar: no basta


def test_listed_total_reads_the_count_the_page_announces():
    from agenda.sources.zona_colonial import listed_total

    assert listed_total('<span class="font-bold" id="ehm-active-count">31</span> eventos') == 31
    assert listed_total("<html></html>") is None
