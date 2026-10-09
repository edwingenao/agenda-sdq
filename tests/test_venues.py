"""Pruebas de los lugares (agenda/venues.json y agenda/venues.py)."""

import json
from datetime import date

import pytest

from agenda import venues
from agenda.db import DB
from agenda.export import export_json
from agenda.models import ZONES, Event, zone_for

BOOK = venues.default()

# Texto `venue` tal como salió de las fuentes (docs/events.json del 9 oct 2026 + SIC) -> id del lugar.
REAL = {
    "ASR Galería": "asr-galeria",
    "Acropolis Business Mall": "acropolis-business-mall",
    "Auditorio Casa San Pablo": "auditorio-casa-san-pablo",
    "Auditorio Horacio Álvarez Saviñón, UNPHU": "unphu",
    "Auditorio Patrick N. Hughson": "auditorio-patrick-hughson",
    "Auditorio Profesor Juan Boch": "auditorio-juan-boch",
    "Av. Lope de Vega no. 29": "lope-de-vega-29",
    "Bar Juan Lockward del Teatro Nacional": "teatro-nacional",
    "Bar Room Republica Brewing": "republica-brewing",
    "Biblioteca Pedro Mir, Auditorio Manuel Del Cabral": "biblioteca-pedro-mir",
    "Bloom SDQ": "bloom-sdq",
    "C. 19 de Marzo 113": "calle-19-de-marzo-113",
    "CCESD": "centro-cultural-de-espana",
    "Café Teatro Juan Lockward, Teatro Nacional": "teatro-nacional",
    "Caribbean Cinemas, Galería 360": "galeria-360",
    "Casa de Teatro": "casa-de-teatro",
    "Casa de Teatro. Olga Cerpa & Mestisay. Muisca de las Islas Canarias": "casa-de-teatro",
    "Centro Comunitario": "centro-comunitario",
    "Centro Cultural de España": "centro-cultural-de-espana",
    "Cielo Room": "cielo-room",
    "Cine Teatro ISSFFAA ( El millon )": "cine-teatro-issffaa",
    "Cinemateca Dominicana": "cinemateca-dominicana",
    "Dominican Fiesta Hotel & Casino": "dominican-fiesta",
    "ENAD (Escuela Nacional de Arte Dramático)": "enad",
    "Escenario 360": "escenario-360",
    "Estadio Olímpico Félix Sánchez": "estadio-olimpico",
    "Ferro Café": "ferro-cafe",
    "Fuerzas Armadas, Salón Independencia": "fuerzas-armadas-salon-independencia",
    "Galeria 360 - Cosas Maravillosas": "galeria-360",
    "Galería 360": "galeria-360",
    "Gran Salón Edmundo Félix Cuevas, Club Arroyo Hondo": "club-arroyo-hondo",
    "Hard Rock Cafe": "hard-rock-cafe",
    "Hard Rock Cafe Blue Mall": "hard-rock-cafe",
    "Hard Rock Cafe Santo Domingo": "hard-rock-cafe",
    "Hotel Crowne Plaza": "hotel-crowne-plaza",
    "Iglesia Metodista Libre": "iglesia-metodista-libre",
    "InterContinental Real Santo Domingo by IHG": "intercontinental-real",
    "Izbira Centro de Eventos": "izbira",
    "Jardin Botanico": "jardin-botanico",
    "Jardin Secreto": "jardin-secreto",
    "Jardín Botánico Nacional Dr. Rafael María Moscoso": "jardin-botanico",
    "Local 3 : Calle Max. Herriquez Ureña 33": "max-henriquez-urena-33",
    "Los Reales Colonial": "los-reales-colonial",
    "Lucia SDQ": "lucia-sdq",
    "Lyle O. Reitzel Arte Contemporáneo, Torre Piantini (Av. Gustavo Mejía Ricart 196, Piantini)": "lyle-o-reitzel",
    "Nash House Club": "nash-house-club",
    "Pabellon de la Fama": "pabellon-fama-deporte",
    "Pabellon de la Fama del Deporte Dominicano": "pabellon-fama-deporte",
    "Ramada by Wyndham Princess Santo Domingo": "ramada-princess",
    "Republica Brewing Draft Room": "republica-brewing",
    "Ruinas de San Francisco, calle Hostos, Zona Colonial": "ruinas-san-francisco",
    "Sala Aida Bonnelly de Díaz, Teatro Nacional": "teatro-nacional",
    "Sala Carlos Piantini, Teatro Nacional": "teatro-nacional",
    "Sala José de Jesus Ravelo, Teatro Nacional": "teatro-nacional",
    "Sala Manuel Rueda": "sala-manuel-rueda",
    "Sala Manuel Rueda, Plaza Iberoamérica": "sala-manuel-rueda",
    "Sala Manuel Rueda: Escuela de Bellas Artes": "sala-manuel-rueda",
    "Salón de Eventos Sambil": "sambil",
    "Sambil": "sambil",
    "Seven Lounge": "seven-lounge",
    "Teatro Guloya": "teatro-guloya",
    "Teatro Guloya, Arzobispo Portes 205, Ciudad Colonial": "teatro-guloya",
    "Teatro Las Máscaras": "teatro-las-mascaras",
    "Teatro Lope de Vega Santo Domingo": "teatro-lope-de-vega",
    "Teatro Nacional Eduardo Brito": "teatro-nacional",
    "The Box Working Space": "the-box-working-space",
    "The Green Room": "the-green-room",
    "The velvet room": "velvet-room",
    "Universidad Nacional Pedro Henríquez Ureña": "unphu",
    "Velvet Room": "velvet-room",
    "Velvet Room SDQ": "velvet-room",
    "Villa Palmera Business Center": "villa-palmera",
    # SIC-RD (el texto trae sala y edificio juntos)
    "Teatro Nacional - Sala Aída Bonelly de Díaz": "teatro-nacional",
    "Sala Aída Bonnelly del Teatro Nacional": "teatro-nacional",
    "Auditorio Museo de Arte Moderno, Pabellón de Identidad y Ciudadanía, Plaza de la Cultura": "museo-arte-moderno",
    "Museo de Arte Moderno - Pabellón Identidad y Ciudadanía": "museo-arte-moderno",
}


# ----------------------------------------------------------------- el archivo ---

def test_shipped_file_loads_and_is_valid():
    assert len(BOOK.venues) >= 60
    assert len({v.id for v in BOOK.venues}) == len(BOOK.venues)


def test_every_coordinate_has_source_precision_and_is_unverified_until_checked():
    located = [v for v in BOOK.venues if v.has_coords]
    assert located, "debe haber al menos un lugar ubicado"
    for v in located:
        assert v.coord_source and v.precision in venues.PRECISIONS
    # Nadie ha comprobado todavía los marcadores en el mapa: si esto cambia, que sea a propósito.
    assert not any(v.verified for v in BOOK.venues)


def test_known_coordinates_come_from_their_cited_source():
    tn = BOOK.by_id["teatro-nacional"]
    assert (tn.lat, tn.lng, tn.precision) == (18.47056, -69.91083, "edificio")
    assert "Wikipedia" in tn.coord_source
    sf = BOOK.by_id["ruinas-san-francisco"]
    assert (sf.lat, sf.lng) == (18.47694, -69.88567)
    # Los lugares dentro de la Plaza de la Cultura no se hacen pasar por el edificio del teatro.
    for vid in ("plaza-de-la-cultura", "museo-arte-moderno", "cinemateca-dominicana", "museo-historia-natural"):
        assert BOOK.by_id[vid].precision == "sector"


def test_unlocated_venues_have_no_invented_coordinates():
    for vid in ("casa-de-teatro", "teatro-las-mascaras", "teatro-guloya", "the-green-room", "sambil"):
        v = BOOK.by_id[vid]
        assert not v.has_coords and v.precision is None and v.coord_source is None


def test_addresses_only_where_a_source_publishes_one():
    assert BOOK.by_id["teatro-guloya"].address == "Arzobispo Portes 205, Ciudad Colonial"
    assert BOOK.by_id["casa-de-teatro"].address is None


# ---------------------------------------------------------------- búsqueda ---

@pytest.mark.parametrize("text,vid", sorted(REAL.items()))
def test_real_venue_texts_resolve(text, vid):
    found = BOOK.find(text)
    assert found is not None and found.id == vid


def test_longest_alias_wins():
    # Contiene "Museo de Arte Moderno" y "Plaza de la Cultura": gana el más específico.
    text = "Auditorio Museo de Arte Moderno, Plaza de la Cultura"
    assert BOOK.find(text).id == "museo-arte-moderno"
    assert BOOK.find("Plaza de la Cultura").id == "plaza-de-la-cultura"
    # La dirección de TIX no se confunde con el Teatro Lope de Vega.
    assert BOOK.find("Av. Lope de Vega no. 29").id == "lope-de-vega-29"
    assert BOOK.find("Teatro Lope de Vega Santo Domingo").id == "teatro-lope-de-vega"


def test_matching_ignores_accents_case_and_punctuation():
    assert BOOK.find("TEATRO NACIONAL, SALA AÍDA BONNELLY").id == "teatro-nacional"
    assert BOOK.find("teatro   las mascaras").id == "teatro-las-mascaras"


def test_aliases_match_whole_words_only():
    assert BOOK.find("Sambilandia") is None
    assert BOOK.find("Escenario 3600") is None


@pytest.mark.parametrize("text", [None, "", "   ", "Lugar que no existe", "Online"])
def test_unknown_or_empty_text_returns_none(text):
    assert BOOK.find(text) is None


def test_every_zone_in_models_has_a_venue_with_the_same_zone():
    street_or_area = {"las damas", "zona colonial", "ciudad colonial"}
    for fragment, zone in ZONES:
        if fragment in street_or_area:
            continue
        found = BOOK.find(fragment)
        assert found is not None, f"{fragment!r} está en ZONES pero no en venues.json"
        assert found.zone == zone, f"{fragment!r}: ZONES dice {zone!r}, venues.json dice {found.zone!r}"


def test_venue_zones_never_contradict_models_zones():
    for v in BOOK.venues:
        for text in (v.name, *v.aliases):
            zone = zone_for(text)
            if zone and v.zone:
                assert zone == v.zone, f"{v.id}: {text!r} cae en {zone!r} pero el lugar dice {v.zone!r}"


# -------------------------------------------------------------- validación ---

def _write(tmp_path, *entries):
    path = tmp_path / "venues.json"
    path.write_text(json.dumps({"venues": list(entries)}), encoding="utf-8")
    return path


def _v(**over):
    base = {"id": "uno", "name": "Uno", "aliases": ["Lugar uno"]}
    base.update(over)
    return base


GOOD_COORDS = dict(lat=18.47, lng=-69.91, precision="edificio", coord_source="Wikipedia")


def test_valid_minimal_and_located_entries_load(tmp_path):
    book = venues.load(_write(tmp_path, _v(), _v(id="dos", aliases=["Lugar dos"], **GOOD_COORDS)))
    assert not book.by_id["uno"].has_coords and book.by_id["dos"].has_coords


@pytest.mark.parametrize(
    "over",
    [
        {"id": "Con Mayúsculas"},
        {"id": ""},
        {"name": "  "},
        {"aliases": []},
        {"aliases": "Lugar uno"},
        {"aliases": ["ab"]},
        {"aliases": ["  "]},
        {**GOOD_COORDS, "lng": 69.91},  # signo cambiado: cae en el desierto
        {**GOOD_COORDS, "lat": 48.47},  # dígito cambiado
        {**GOOD_COORDS, "lng": None},  # lat sin lng
        {**GOOD_COORDS, "coord_source": ""},  # coordenada sin fuente
        {**GOOD_COORDS, "coord_source": None},
        {**GOOD_COORDS, "precision": "exacta"},
        {**GOOD_COORDS, "precision": None},
        {"precision": "edificio"},  # precisión sin coordenadas
        {"verified": True},  # verificado sin coordenadas
        {"verified": "si"},
        {**GOOD_COORDS, "lat": "18.47"},
        {**GOOD_COORDS, "lat": True},
    ],
)
def test_invalid_entries_raise(tmp_path, over):
    with pytest.raises(ValueError):
        venues.load(_write(tmp_path, _v(**over)))


def test_duplicate_ids_and_aliases_raise(tmp_path):
    with pytest.raises(ValueError, match="id repetido"):
        venues.load(_write(tmp_path, _v(), _v(aliases=["Otro"])))
    with pytest.raises(ValueError, match="alias repetido"):
        venues.load(_write(tmp_path, _v(), _v(id="dos", aliases=["LUGAR   UNO"])))
    with pytest.raises(ValueError, match="alias repetido"):
        venues.load(_write(tmp_path, _v(aliases=["Café"]), _v(id="dos", aliases=["Cafe"])))


@pytest.mark.parametrize("bad", [{}, {"venues": "x"}, {"venues": {"a": 1}}, [], None])
def test_unreadable_structure_raises(tmp_path, bad):
    path = tmp_path / "venues.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        venues.load(path)


# ------------------------------------------------------------------ export ---

def _event(title, venue, source="teatro_nacional", url=None):
    return Event(
        source=source, source_name=source, url=url or f"https://{source}/{title}", title=title,
        dates=["2026-10-15"], start_time="20:00", venue=venue,
    )


def test_export_adds_coordinates_and_writes_venues_file(tmp_path):
    db = DB(":memory:")
    now = "2026-10-09T00:00:00"
    db.upsert_event(_event("Concierto A", "Sala Carlos Piantini, Teatro Nacional"), now)
    db.upsert_event(_event("Concierto B", "Casa de Teatro", source="casa_de_teatro"), now)
    db.upsert_event(_event("Concierto C", "Un bar que nadie registró", source="tix"), now)
    db.upsert_event(_event("Concierto D", "", source="ticketmax"), now)
    logs = []
    out = tmp_path / "docs" / "events.json"
    assert export_json(db, out, date(2026, 10, 9), log=logs.append) == 4
    by_title = {e["title"]: e for e in json.loads(out.read_text(encoding="utf-8"))["events"]}

    a = by_title["Concierto A"]
    assert (a["venueId"], a["lat"], a["lng"], a["geoPrecision"]) == ("teatro-nacional", 18.47056, -69.91083, "edificio")
    b = by_title["Concierto B"]  # lugar conocido pero sin coordenadas: lleva id, nunca un marcador inventado
    assert b["venueId"] == "casa-de-teatro" and "lat" not in b and "lng" not in b and "geoPrecision" not in b
    for title in ("Concierto C", "Concierto D"):
        assert not {"venueId", "lat", "lng"} & set(by_title[title])

    places = json.loads((tmp_path / "docs" / "venues.json").read_text(encoding="utf-8"))
    assert places["count"] == 2 and [v["id"] for v in places["venues"]] == ["casa-de-teatro", "teatro-nacional"]
    assert set(places["venues"][0]) == {"id", "name", "address", "zone", "lat", "lng", "precision"}
    assert any("Un bar que nadie registró" in line for line in logs)
    assert any("sin coordenadas" in line and "Casa de Teatro" in line for line in logs)


def test_export_survives_a_broken_venues_file(tmp_path, monkeypatch):
    def boom():
        raise ValueError("archivo roto")

    monkeypatch.setattr(venues, "default", boom)
    db = DB(":memory:")
    db.upsert_event(_event("Concierto A", "Teatro Nacional"), "2026-10-09T00:00:00")
    logs = []
    out = tmp_path / "events.json"
    assert export_json(db, out, date(2026, 10, 9), log=logs.append) == 1
    event = json.loads(out.read_text(encoding="utf-8"))["events"][0]
    assert "venueId" not in event and any("AVISO" in line for line in logs)
    assert not (tmp_path / "venues.json").exists()
