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
