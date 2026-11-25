"""Pruebas de la geocodificación con OpenStreetMap (todas sin red: `fetch` es falso)."""

import json
from datetime import date

import pytest

from agenda import geocode, venues
from agenda.http import Disallowed

TODAY = date(2026, 10, 9)


def hit(name, lat, lon, cls="amenity", typ="theatre", osm_type="way", osm_id=1):
    return {"display_name": name, "lat": str(lat), "lon": str(lon), "category": cls, "type": typ,
            "osm_type": osm_type, "osm_id": osm_id}


CASA = hit("Casa de Teatro, Arzobispo Meriño, Ciudad Colonial, Santo Domingo, República Dominicana", 18.4757, -69.8841,
           osm_id=111)


def fake(*payloads):
    """fetch falso: cada llamada devuelve el siguiente payload (el último se repite) y guarda los parámetros."""
    calls = []

    def fetch(params):
        calls.append(params)
        return payloads[min(len(calls), len(payloads)) - 1]

    fetch.calls = calls
    return fetch


def make_file(tmp_path, *extra):
    base = [
        {"id": "casa-de-teatro", "name": "Casa de Teatro", "aliases": ["Casa de Teatro"], "zone": "Ciudad Colonial"},
        {"id": "teatro-nacional", "name": "Teatro Nacional Eduardo Brito", "aliases": ["Teatro Nacional"],
         "lat": 18.47056, "lng": -69.91083, "precision": "edificio", "coord_source": "Wikipedia"},
    ]
    path = tmp_path / "venues.json"
    path.write_text(json.dumps({"venues": base + list(extra)}, ensure_ascii=False), encoding="utf-8")
    return path


def run(tmp_path, fetch, **kw):
    path = make_file(tmp_path, *kw.pop("extra", []))
    rows = geocode.run(path, fetch=fetch, today=TODAY, report_path=tmp_path / "informe.md", log=lambda *_: None, **kw)
    return path, rows


def saved(path):
    return {v["id"]: v for v in json.loads(path.read_text(encoding="utf-8"))["venues"]}


# --------------------------------------------------------------- piezas ---

def test_params_ask_for_santo_domingo_only_and_identify_the_language():
    p = geocode.params_for("Casa de Teatro, Santo Domingo")
    assert p["countrycodes"] == "do" and p["bounded"] == "1" and p["format"] == "jsonv2"
    left, top, right, bottom = map(float, p["viewbox"].split(","))
    assert (left, top, right, bottom) == (venues.BBOX[2], venues.BBOX[1], venues.BBOX[3], venues.BBOX[0])


def test_parse_skips_malformed_items():
    items = [CASA, {"lat": "x"}, {"lat": "1", "lon": "2"}, "basura", None]
    assert [c.osm_id for c in geocode.parse(items)] == [111]
    assert geocode.parse({"error": "x"}) == []


@pytest.mark.parametrize("cls,expected", [("amenity", "edificio"), ("tourism", "edificio"), ("historic", "edificio"),
                                          ("highway", "calle"), ("place", "sector"), ("boundary", "sector")])
def test_precision_depends_on_what_openstreetmap_found(cls, expected):
    assert geocode.precision_for(geocode.parse([hit("x", 18.47, -69.9, cls=cls)])[0]) == expected


def test_distance_is_in_meters():
    assert geocode.distance_m(18.47, -69.91, 18.47, -69.91) == 0
    assert 105 < geocode.distance_m(18.47, -69.91, 18.471, -69.91) < 117  # 0,001° de latitud ≈ 111 m


def test_queries_use_the_address_when_there_is_one():
    assert geocode.queries_for({"name": "Casa de Teatro"}) == ["Casa de Teatro, Santo Domingo, República Dominicana"]
    qs = geocode.queries_for({"name": "Teatro Guloya", "address": "Arzobispo Portes 205, Ciudad Colonial"})
    assert len(qs) == 2 and qs[1].startswith("Arzobispo Portes 205")


# ----------------------------------------------------------- resultados ---

def test_good_result_is_picked_but_not_applied_by_default(tmp_path):
    path, rows = run(tmp_path, fake([CASA]))
    assert [r.venue_id for r in rows] == ["casa-de-teatro"]  # el que ya tiene coordenadas no se consulta
    assert rows[0].pick.ref == "way/111"
    assert saved(path)["casa-de-teatro"].get("lat") is None  # sin --aplicar el archivo no cambia
    report = (tmp_path / "informe.md").read_text(encoding="utf-8")
    assert "se aplicaría" in report and "openstreetmap.org/way/111" in report and "ODbL" in report


def test_apply_writes_coordinates_with_source_and_unverified(tmp_path):
    path, _ = run(tmp_path, fake([CASA]), aplicar=True)
    v = saved(path)["casa-de-teatro"]
    assert (v["lat"], v["lng"], v["precision"], v["verified"]) == (18.4757, -69.8841, "edificio", False)
    assert "OpenStreetMap" in v["coord_source"] and "way/111" in v["coord_source"] and "2026-10-09" in v["coord_source"]
    assert v["zone"] == "Ciudad Colonial"  # no se pierde lo que ya había
    venues.load(path)  # el archivo resultante sigue siendo válido


def test_apply_never_overwrites_existing_coordinates(tmp_path):
    other = hit("Teatro Nacional, Santo Domingo", 18.5, -69.9, osm_id=9)
    path, rows = run(tmp_path, fake([CASA]), aplicar=True)
    assert saved(path)["teatro-nacional"]["lat"] == 18.47056
    path2, rows2 = run(tmp_path, fake([other]), aplicar=True, revisar=True)
    assert saved(path2)["teatro-nacional"]["lat"] == 18.47056  # --revisar solo compara


def test_review_reports_distance_without_writing(tmp_path):
    near = hit("Teatro Nacional Eduardo Brito, Santo Domingo", 18.4706, -69.9109, osm_id=5)
    path, rows = run(tmp_path, fake([near]), revisar=True)
    tn = next(r for r in rows if r.venue_id == "teatro-nacional")
    assert tn.distance_m is not None and tn.distance_m < 50
    assert "solo comparado" in (tmp_path / "informe.md").read_text(encoding="utf-8")


def test_result_outside_santo_domingo_is_rejected(tmp_path):
    far = hit("Casa de Teatro, Santiago de los Caballeros", 19.45, -70.69)
    path, rows = run(tmp_path, fake([far]), aplicar=True)
    assert rows[0].pick is None and "Santo Domingo" in rows[0].note
    assert saved(path)["casa-de-teatro"].get("lat") is None


def test_result_with_unrelated_name_is_not_applied(tmp_path):
    other = hit("Colmado La Esquina, Santo Domingo", 18.48, -69.9)
    path, rows = run(tmp_path, fake([other]), aplicar=True)
    assert rows[0].pick is None and "no se parece" in rows[0].note
    assert saved(path)["casa-de-teatro"].get("lat") is None
    assert "Colmado La Esquina" in (tmp_path / "informe.md").read_text(encoding="utf-8")  # queda para revisión


def test_no_results_is_reported(tmp_path):
    path, rows = run(tmp_path, fake([]), aplicar=True)
    assert rows[0].pick is None and rows[0].note == "sin resultados"


def test_second_query_with_the_address_is_tried_when_the_first_fails(tmp_path):
    guloya = {"id": "teatro-guloya", "name": "Teatro Guloya", "aliases": ["Teatro Guloya"],
              "address": "Arzobispo Portes 205, Ciudad Colonial"}
    ok = hit("Teatro Guloya, Arzobispo Portes, Ciudad Colonial, Santo Domingo", 18.4793, -69.8861, osm_id=77)
    fetch = fake([], [CASA], [ok])  # casa-de-teatro: 1 consulta; guloya: nombre sin resultados, luego la dirección
    path, rows = run(tmp_path, fetch, extra=[guloya], aplicar=True, solo=["casa-de-teatro", "teatro-guloya"])
    assert len(fetch.calls) == 3 and fetch.calls[2]["q"].startswith("Arzobispo Portes 205")
    assert saved(path)["teatro-guloya"]["lat"] == 18.4793


def test_only_selected_venues_are_queried(tmp_path):
    other = {"id": "sambil", "name": "Sambil Santo Domingo", "aliases": ["Sambil"]}
    fetch = fake([CASA])
    run(tmp_path, fetch, extra=[other], solo=["sambil"])
    assert len(fetch.calls) == 1 and "Sambil" in fetch.calls[0]["q"]


# ------------------------------------------------------------- robustez ---

def test_robots_disallow_stops_the_run_and_leaves_manual_links(tmp_path):
    def blocked(params):
        raise Disallowed("robots.txt no permite https://nominatim.openstreetmap.org/search")

    path, rows = run(tmp_path, blocked, aplicar=True)
    assert rows == [] and saved(path)["casa-de-teatro"].get("lat") is None
    report = (tmp_path / "informe.md").read_text(encoding="utf-8")
    assert "Se detuvo" in report and "robots.txt" in report


def test_one_failing_venue_does_not_stop_the_others(tmp_path):
    sambil = {"id": "sambil", "name": "Sambil Santo Domingo", "aliases": ["Sambil"]}
    good = hit("Sambil, Santo Domingo", 18.4826, -69.9137, cls="shop", typ="mall", osm_id=3)
    state = {"n": 0}

    def flaky(params):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError("sin red")
        return [good]

    path, rows = run(tmp_path, flaky, extra=[sambil], aplicar=True)
    assert "error al consultar" in rows[0].note and rows[1].pick is not None
    assert saved(path)["sambil"]["lat"] == 18.4826


def test_a_broken_venues_file_fails_before_any_request(tmp_path):
    path = tmp_path / "venues.json"
    path.write_text(json.dumps({"venues": [{"id": "x", "name": "X", "aliases": ["Equis"], "lat": 18.4}]}),
                    encoding="utf-8")
    fetch = fake([])
    with pytest.raises(ValueError):
        geocode.run(path, fetch=fetch, today=TODAY, report_path=None, log=lambda *_: None)
    assert fetch.calls == []
