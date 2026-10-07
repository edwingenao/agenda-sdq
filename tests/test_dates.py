from datetime import date

import pytest

from agenda.dates import find_dates, parse_price, parse_time
from agenda.models import normalize_category

TODAY = date(2026, 10, 5)


def d(*args):
    return date(*args)


def test_long_date_with_year():
    assert find_dates("Fecha: 7 de octubre, 2026", TODAY) == [d(2026, 10, 7)]


def test_long_date_without_year_infers_current():
    assert find_dates("jueves 15 de octubre", TODAY) == [d(2026, 10, 15)]


def test_date_without_year_rolls_to_next_year():
    assert find_dates("10 de enero", TODAY) == [d(2027, 1, 10)]


def test_range_returns_both_ends_once():
    assert find_dates("Del 9 al 18 de octubre, 2026", TODAY) == [d(2026, 10, 9), d(2026, 10, 18)]


def test_list_of_two_days():
    assert find_dates("7 y 8 de octubre", TODAY) == [d(2026, 10, 7), d(2026, 10, 8)]


def test_cce_slash_format_multiple_sessions():
    txt = "17/Oct/2026 24/Oct/2026 31/Oct/2026 07/Nov/2026"
    assert find_dates(txt, TODAY, only_slash=True) == [
        d(2026, 10, 17), d(2026, 10, 24), d(2026, 10, 31), d(2026, 11, 7)
    ]


def test_numeric_date():
    assert find_dates("25/09/2026", TODAY) == [d(2026, 9, 25)]


def test_month_day_pattern_zona_colonial():
    assert find_dates("OCT 06", TODAY, month_day_pattern=True) == [d(2026, 10, 6)]
    assert find_dates("OCT 06", TODAY) == []  # sin el patrón, no se confunde con texto libre


def test_invalid_date_ignored():
    assert find_dates("31 de febrero de 2026", TODAY) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("10 am a 1 pm", "10:00"),
        ("8:30 p. m.", "20:30"),
        ("a las 8:30 pm", "20:30"),
        ("20:30", "20:30"),
        ("12 pm", "12:00"),
        ("12 am", "00:00"),
        ("sin hora", None),
    ],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Entrada Gratis", (True, 0, 0)),
        ("Gratuito (Entrada libre hasta completar aforo)", (True, 0, 0)),
        ("$1200", (False, 1200, 1200)),
        ("RD$2,290.00\nRD$1,730.00", (False, 1730, 2290)),
        ("RD$ 500", (False, 500, 500)),
        ("$1.200", (False, 1200, 1200)),
        ("nada que ver", (None, None, None)),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Música / Sonido", "Música"),
        ("Cine / Audiovisual", "Cine"),
        ("Proyección Audiovisual", "Cine"),
        ("Ópera / Lírica", "Música"),
        ("Comedia", "Teatro"),
        ("Danza", "Danza"),
        ("Exposición", "Arte"),
        ("Performance en vivo", "Arte"),
        ("Video mapping y escena digital", "Arte"),
        ("Muestra colectiva de jóvenes artistas", "Arte"),
        ("Instalación artística", "Arte"),
        ("Inauguración con curaduría de Ana Pérez", "Arte"),
        ("Teatro musical: Los Miserables", "Teatro"),
        ("Comedia musical", "Teatro"),
        ("Noche musical en el malecón", "Música"),
        ("Monólogo", "Teatro"),
        ("Conferencia / Charla", "Cultura"),
        ("Formación", "Cultura"),
    ],
)
def test_category(text, expected):
    assert normalize_category(text) == expected
