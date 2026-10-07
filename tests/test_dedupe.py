import unittest
from datetime import datetime

from agenda.dedupe import Event, dedupe, is_same_event, norm_venue, title_similarity


def dt(d, h=None, m=0):
    return datetime(2026, 10, d, h or 0, m)


class TestDedupe(unittest.TestCase):
    def test_retro_jazz_entre_teatro_nacional_y_blog(self):
        tn = Event("Retro Jazz", dt(9, 20), "teatro_nacional",
                   venue="Teatro Nacional Eduardo Brito",
                   url="https://tn/retro", price_min=500, price_max=500, is_free=False)
        blog = Event("Retro Jazz: Noche de standards", dt(9), "jazz_dominicana",
                     venue="Teatro Nacional", has_time=False, url="https://blog/x",
                     description="Descripción más larga desde el blog.")
        out = dedupe([blog, tn])
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e.source, "teatro_nacional")
        self.assertEqual(e.start.hour, 20)
        self.assertEqual(e.price_min, 500)
        self.assertEqual(e.description, "Descripción más larga desde el blog.")
        self.assertEqual(len(e.sources), 2)

    def test_mismo_titulo_distinta_sede_no_se_une(self):
        a = Event("Cine español", dt(7, 19), "casa_teatro", venue="Casa de Teatro")
        b = Event("Cine español", dt(7, 19), "cce", venue="Centro Cultural de España")
        self.assertFalse(is_same_event(a, b))
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_distinto_dia_no_se_une(self):
        a = Event("Retro Jazz", dt(9, 20), "teatro_nacional", venue="Teatro Nacional")
        b = Event("Retro Jazz", dt(16, 20), "jazz_dominicana", venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_misma_fuente_nunca_se_une(self):
        a = Event("Danza Joven", dt(10, 18), "teatro_nacional", venue="Teatro Nacional")
        b = Event("Danza Joven", dt(10, 18), "teatro_nacional", venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_dos_funciones_mismo_dia_horas_lejanas(self):
        a = Event("Danza Joven", dt(10, 15), "teatro_nacional", venue="Teatro Nacional")
        b = Event("Danza Joven", dt(10, 20), "jazz_dominicana", venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_titulo_generico_corto_no_une_todo(self):
        a = Event("Jazz", dt(9, 20), "teatro_nacional", venue="Teatro Nacional")
        b = Event("Retro Jazz Quartet", dt(9, 20), "jazz_dominicana", venue="Teatro Nacional")
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_acentos_y_mayusculas(self):
        self.assertGreaterEqual(title_similarity("Concierto de Cámara", "CONCIERTO DE CAMARA"), 0.85)

    def test_conflicto_de_precio_se_marca(self):
        a = Event("Wagner / Molina", dt(11, 20), "teatro_nacional", venue="Teatro Nacional",
                  price_min=610, price_max=2290, is_free=False)
        b = Event("Wagner Molina", dt(11, 20), "zonacolonial", venue="Teatro Nacional",
                  price_min=500, price_max=2000, is_free=False)
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].price_min, 610)      # gana la fuente de mayor prioridad
        self.assertTrue(any("precio" in c for c in out[0].conflicts))

    def test_precio_desconocido_no_pisa_precio_conocido(self):
        a = Event("Agatha + Medulah", dt(12, 21), "jazz_dominicana", venue="Casa de Teatro")
        b = Event("Agatha y Medulah", dt(12, 21), "casa_teatro", venue="Casa de Teatro",
                  price_min=400, price_max=400, is_free=False)
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].price_min, 400)

    def test_alias_de_sedes(self):
        self.assertEqual(norm_venue("Teatro Nacional, Sala Carlos Piantini"), "teatro nacional")
        self.assertEqual(norm_venue("Centro Cultural de España"), "cce")

    def test_orden_de_entrada_no_importa(self):
        tn = Event("Retro Jazz", dt(9, 20), "teatro_nacional", venue="Teatro Nacional")
        blog = Event("Retro Jazz", dt(9), "jazz_dominicana", venue="Teatro Nacional", has_time=False)
        self.assertEqual(len(dedupe([tn, blog])), 1)
        self.assertEqual(len(dedupe([blog, tn])), 1)


if __name__ == "__main__":
    unittest.main()
