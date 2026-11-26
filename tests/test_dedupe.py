import unittest

from agenda.dedupe import dedupe, is_same_event, norm_venue, title_similarity
from agenda.models import Event


def ev(title, d, source, h=None, m=0, url=None, **kw):
    """Evento del 2026-10-d; sin h, la fuente solo trae la fecha."""
    return Event(
        source=source,
        source_name=source,
        url=url or f"https://{source}/{title}",
        title=title,
        dates=[f"2026-10-{d:02d}"],
        start_time=f"{h:02d}:{m:02d}" if h is not None else None,
        **kw,
    )


class TestDedupe(unittest.TestCase):
    def test_retro_jazz_entre_teatro_nacional_y_blog(self):
        tn = ev("Retro Jazz", 9, "teatro_nacional", 20,
                venue="Teatro Nacional Eduardo Brito",
                url="https://tn/retro", price_min=500, price_max=500, is_free=False)
        blog = ev("Retro Jazz: Noche de standards", 9, "jazz_en_dominicana",
                  venue="Teatro Nacional", url="https://blog/x",
                  description="Descripción más larga desde el blog.")
        out = dedupe([blog, tn])
        self.assertEqual(len(out), 1)
        e = out[0].event
        self.assertEqual(e.source, "teatro_nacional")
        self.assertEqual(e.url, "https://tn/retro")
        self.assertEqual(e.start_time, "20:00")
        self.assertEqual(e.price_min, 500)
        self.assertEqual(e.description, "Descripción más larga desde el blog.")
        self.assertEqual([s["id"] for s in out[0].sources], ["teatro_nacional", "jazz_en_dominicana"])

    def test_mismo_titulo_distinta_sede_no_se_une(self):
        a = ev("Cine español", 7, "casa_de_teatro", 19, venue="Casa de Teatro")
        b = ev("Cine español", 7, "cce", 19, venue="Centro Cultural de España")
        self.assertFalse(is_same_event(a, b))
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_distinto_dia_no_se_une(self):
        a = ev("Retro Jazz", 9, "teatro_nacional", 20, venue="Teatro Nacional")
        b = ev("Retro Jazz", 16, "jazz_en_dominicana", 20, venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_misma_fuente_nunca_se_une(self):
        a = ev("Danza Joven", 10, "teatro_nacional", 18, venue="Teatro Nacional", url="https://tn/1")
        b = ev("Danza Joven", 10, "teatro_nacional", 18, venue="Teatro Nacional", url="https://tn/2")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_dos_funciones_mismo_dia_horas_lejanas(self):
        a = ev("Danza Joven", 10, "teatro_nacional", 15, venue="Teatro Nacional")
        b = ev("Danza Joven", 10, "jazz_en_dominicana", 20, venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_titulo_generico_corto_no_une_todo(self):
        a = ev("Jazz", 9, "teatro_nacional", 20, venue="Teatro Nacional")
        b = ev("Retro Jazz Quartet", 9, "jazz_en_dominicana", 20, venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_acentos_y_mayusculas(self):
        self.assertGreaterEqual(title_similarity("Concierto de Cámara", "CONCIERTO DE CAMARA"), 0.85)

    def test_conflicto_de_precio_se_marca(self):
        a = ev("Wagner / Molina", 11, "teatro_nacional", 20, venue="Teatro Nacional",
               price_min=610, price_max=2290, is_free=False)
        b = ev("Wagner Molina", 11, "zona_colonial", 20, venue="Teatro Nacional",
               price_min=500, price_max=2000, is_free=False)
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].event.price_min, 610)      # gana la fuente de mayor prioridad
        self.assertTrue(any("precio" in c for c in out[0].conflicts))

    def test_precio_desconocido_no_pisa_precio_conocido(self):
        a = ev("Agatha + Medulah", 12, "jazz_en_dominicana", 21, venue="Casa de Teatro")
        b = ev("Agatha y Medulah", 12, "casa_de_teatro", 21, venue="Casa de Teatro",
               price_min=400, price_max=400, is_free=False)
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].event.price_min, 400)

    def test_categoria_especifica_gana_a_cultura(self):
        a = ev("Rojo", 9, "teatro_nacional", 20, venue="Teatro Nacional")  # categoría por defecto
        b = ev("Rojo", 9, "zona_colonial", 20, venue="Teatro Nacional", category="Teatro")
        self.assertEqual(dedupe([a, b])[0].event.category, "Teatro")

    def test_no_modifica_los_eventos_de_entrada(self):
        a = ev("Retro Jazz", 9, "teatro_nacional", venue="Teatro Nacional")
        b = ev("Retro Jazz", 9, "jazz_en_dominicana", 20, venue="Teatro Nacional")
        dedupe([a, b])
        self.assertIsNone(a.start_time)

    def test_alias_de_sedes(self):
        self.assertEqual(norm_venue("Teatro Nacional, Sala Carlos Piantini"), "teatro nacional")
        self.assertEqual(norm_venue("Centro Cultural de España"), "cce")

    def test_orden_de_entrada_no_importa(self):
        tn = ev("Retro Jazz", 9, "teatro_nacional", 20, venue="Teatro Nacional")
        blog = ev("Retro Jazz", 9, "jazz_en_dominicana", venue="Teatro Nacional")
        self.assertEqual(len(dedupe([tn, blog])), 1)
        self.assertEqual(len(dedupe([blog, tn])), 1)

    def test_export_une_repetidos_y_lista_las_fuentes(self):
        import json
        import tempfile
        from datetime import date
        from pathlib import Path

        from agenda.db import DB
        from agenda.export import export_json

        db = DB(":memory:")
        db.upsert_event(ev("Laz Santos & La Talent Band", 17, "casa_de_teatro", 21,
                           venue="Casa de Teatro", url="https://casadeteatro.org/e/1",
                           ticket_url="https://boletos/laz"), "2026-10-06T00:00:00")
        db.upsert_event(ev("LAZ SANTOS & LA TALENT BAND", 17, "zona_colonial", 21,
                           venue="Casa de Teatro", url="https://zonacolonial.do/a/laz",
                           is_free=False, price_min=800), "2026-10-06T00:00:00")
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "events.json"
            self.assertEqual(export_json(db, out, date(2026, 10, 6), log=logs.append), 1)
            pub = json.loads(out.read_text(encoding="utf-8"))["events"][0]
        self.assertEqual(pub["srcUrl"], "https://casadeteatro.org/e/1")
        self.assertEqual(pub["ticketUrl"], "https://boletos/laz")
        self.assertEqual(pub["price"], 800)
        self.assertEqual([s["srcUrl"] for s in pub["sources"]],
                         ["https://casadeteatro.org/e/1", "https://zonacolonial.do/a/laz"])
        self.assertTrue(any("unidos" in line for line in logs))

    def test_prioridad_usa_ids_reales_de_las_fuentes(self):
        from agenda.dedupe import SOURCE_PRIORITY
        from agenda.sources import SOURCES
        self.assertEqual(set(SOURCE_PRIORITY), set(SOURCES))


if __name__ == "__main__":
    unittest.main()


def test_containment_tolerates_typos_but_not_different_words():
    from agenda.dedupe import title_similarity

    assert title_similarity("Mahler Resurreción", "Mahler: Resurrección | Gala de aniversarios") >= 0.85
    assert title_similarity("Mahler Titán", "Mahler: Resurrección | Gala de aniversarios") < 0.85
    assert title_similarity("Retro Jazz", "Rock Jazz Quartet") < 0.85


# ---- listados repetidos de la misma fuente y temporadas que empiezan en días distintos (24 nov 2026) ----

def ev_nov(title, d, source, h=None, venue="", end=None, **kw):
    dates = [f"2026-11-{d:02d}"] + ([f"2026-11-{end:02d}"] if end else [])
    return Event(source=source, source_name=source, url=f"https://{source}/{title}", title=title, dates=dates,
                 start_time=f"{h:02d}:00" if h is not None else None, venue=venue, **kw)


def test_ticketmax_same_session_listed_twice_is_merged():
    a = ev_nov("Vino & Tinta 25.11.26 | 6:00 PM - 8:00 PM", 25, "ticketmax", 18, "Centro Cultural Casa Libros", price_min=300)
    b = ev_nov("Vino & Tinta | 6:00 PM - 8:00 PM", 25, "ticketmax", 18, "Centro Cultural Casa Libros", price_min=300)
    out = dedupe([a, b])
    assert len(out) == 1 and len(out[0].sources) == 2


def test_zona_colonial_two_pages_for_the_same_concert_are_merged():
    a = ev_nov("IVANA LOYOLA PRESENTA: “CUERDAS EN EL OCASO”", 27, "zona_colonial", 20, "Casa de Teatro", price_min=1200)
    b = ev_nov("Presentación en vivo del álbum debut “Cuerdas en el Ocaso” (Banda completa) por Ivana Loyola", 27,
               "zona_colonial", 20, "Casa de Teatro", price_min=1000)
    out = dedupe([a, b])
    assert len(out) == 1 and any("precio distinto" in c for c in out[0].conflicts)


def test_same_source_different_time_or_title_stays_separate():
    base = dict(venue="Centro Cultural Casa Libros")
    tarde = ev_nov("Vino & Tinta", 25, "ticketmax", 15, **base)
    noche = ev_nov("Vino & Tinta", 25, "ticketmax", 20, **base)
    otro = ev_nov("Cata de vinos del mundo", 25, "ticketmax", 15, **base)
    assert len(dedupe([tarde, noche])) == 2  # funciones distintas el mismo día
    assert len(dedupe([tarde, otro])) == 2  # misma hora, otro evento
    assert len(dedupe([ev_nov("Vino & Tinta", 25, "ticketmax", 15, end=28, **base), tarde])) == 2  # rango vs función suelta


def test_other_sources_keep_the_old_rule_two_rooms_same_time():
    a = ev_nov("Danza Joven", 10, "teatro_nacional", 18, "Sala Ravelo, Teatro Nacional")
    b = ev_nov("Danza Joven", 10, "teatro_nacional", 18, "Sala Carlos Piantini, Teatro Nacional")
    assert len(dedupe([a, b])) == 2


def test_run_published_by_two_sources_with_different_start_days_is_merged():
    a = ev_nov("Señora, ¿Me Presta su Marido?", 13, "teatro_las_mascaras", None, "Teatro Las Máscaras", end=29, price_min=875)
    b = ev_nov("Señora, ¿me presta su marido?", 24, "tix", None, "Teatro Las Máscaras", end=29)
    out = dedupe([a, b])
    assert len(out) == 1 and out[0].event.source == "teatro_las_mascaras"
    assert any("fechas distintas" in c for c in out[0].conflicts)


def test_runs_that_do_not_overlap_or_lack_a_confirmed_venue_stay_separate():
    a = ev_nov("Señora, ¿me presta su marido?", 1, "teatro_las_mascaras", None, "Teatro Las Máscaras", end=10)
    b = ev_nov("Señora, ¿me presta su marido?", 24, "tix", None, "Teatro Las Máscaras", end=29)
    assert len(dedupe([a, b])) == 2  # temporadas distintas
    c = ev_nov("Señora, ¿me presta su marido?", 13, "teatro_las_mascaras", None, "", end=29)
    assert len(dedupe([c, b])) == 2  # sin sede no se arriesga


def test_gastronomia_category_rules():
    from agenda.models import normalize_category as nc

    assert nc("Vino & Tinta 27.11.26") == "Gastronomía"
    assert nc("Cata de vinos del mundo") == "Gastronomía"
    assert nc("Brunch con chef invitado") == "Gastronomía"
    assert nc("Oktoberfest Santo Domingo") == "Gastronomía"
    assert nc("Noche de jazz y vino") == "Música"  # el concierto sigue siendo música
    assert nc("EL PARTY - LA ÚLTIMA CENA") == "Cultura"  # "cena" suelta no cuenta
    assert nc("Catálogo de la exposición") == "Arte"  # "cata" no es "catálogo"
    assert nc("Concierto de cámara") == "Música"


def test_gastronomia_only_from_the_title_not_the_description():
    from agenda.models import normalize_category as nc

    assert nc("PLAYA ERMITAÑO", "Incluye almuerzo buffet y degustación de agua de coco") == "Cultura"
    assert nc("Noche de cata") == "Gastronomía"
    assert nc("Noche de cata", "Con música en vivo") == "Música"  # Música sigue mandando si la descripción la nombra
