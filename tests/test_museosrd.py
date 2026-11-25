"""Red Nacional de Museos: muestras con el texto visible de dos páginas reales (24 nov 2026) y un sitemap recortado.

No hay HTML real en samples/ (ver el docstring del adaptador): parse_page se prueba con HTML sintético armado
con esas mismas líneas.
"""

from datetime import date
from pathlib import Path

import httpx

from agenda.db import DB
from agenda.http import Fetcher
from agenda.sources import SOURCES
from agenda.sources.museosrd import MuseosRD, parse_lines, parse_page, sitemap_urls

S = Path(__file__).resolve().parent.parent / "samples"
TODAY = date(2026, 11, 24)


def sample(name):
    title, *lines = (S / name).read_text(encoding="utf-8").splitlines()
    return title.split("|")[0].strip(), lines


PLANTAS_URL = "https://museosrd.gob.do/evento/visita-guiada-plantas-endemicas-de-la-espanola/"
CUSTODIA_URL = "https://museosrd.gob.do/evento/la-custodia-arte-y-devocion/"
SITEMAP = (S / "museosrd_job_listing_sitemap.xml").read_text(encoding="utf-8")


def test_free_event_with_everything():
    title, lines = sample("museosrd_plantas_endemicas.txt")
    ev = parse_lines(title, lines, PLANTAS_URL, TODAY)
    assert ev.title == "Visita guiada: Plantas endémicas de La Española"
    assert ev.dates == ["2026-11-28"] and ev.start_time == "18:00"
    assert ev.venue == "Quinta Dominica" and ev.zone == "Ciudad Colonial"
    assert ev.is_free is True and ev.price_min == 0  # «Entrada: Libre, hasta completar aforo»
    assert ev.source == "museosrd" and ev.source_name == "Red Nacional de Museos"
    assert ev.needs_review is False and 0 < len(ev.description) <= 280
    assert "809" not in ev.description


def test_event_without_entry_line_has_unconfirmed_price():
    title, lines = sample("museosrd_custodia.txt")
    ev = parse_lines(title, lines, CUSTODIA_URL, TODAY)
    assert ev.dates == ["2026-12-03"] and ev.start_time == "19:30"
    assert ev.venue == "Museo de la Catedral de Santo Domingo" and ev.zone == "Ciudad Colonial"
    assert ev.is_free is None and ev.price_min is None  # nunca gratis sin que la fuente lo diga
    assert ev.category == "Arte"  # lo asigna normalize_category (menciona «arte» y «platería»)


def test_past_event_is_dropped():
    title, lines = sample("museosrd_plantas_endemicas.txt")
    assert parse_lines(title, lines, PLANTAS_URL, date(2026, 12, 1)) is None


def test_other_city_is_dropped_and_unknown_city_is_flagged():
    title, lines = sample("museosrd_plantas_endemicas.txt")
    santiago = [ln.replace("Calle Padre Billini núm. 202, Ciudad Colonial, Santo Domingo, República Dominicana",
                           "Av. 27 de Febrero, Santiago de los Caballeros") if ln.startswith("Dirección") else ln
                for ln in lines]
    assert parse_lines(title, santiago, PLANTAS_URL, TODAY) is None
    unknown = [ln.replace("Quinta Dominica.", "Sala Principal.") if ln.startswith("Lugar") else
               "Dirección: Calle sin ciudad 5." if ln.startswith("Dirección") else ln for ln in lines]
    ev = parse_lines(title, unknown, PLANTAS_URL, TODAY)
    assert ev is not None and ev.needs_review is True


def test_page_without_date_is_ignored():
    assert parse_lines("Algo", ["Sin etiquetas", "Solo texto largo " * 5], PLANTAS_URL, TODAY) is None


def test_parse_page_from_synthetic_html():
    title, lines = sample("museosrd_custodia.txt")
    html = f"<html><head><title>{title} | MUSEOSRD</title></head><body><h1>{title}</h1>" + "".join(
        f"<p>{ln}</p>" for ln in lines[10:]) + "</body></html>"
    ev = parse_page(html, CUSTODIA_URL, TODAY)
    assert ev.dates == ["2026-12-03"] and ev.start_time == "19:30" and ev.title == title


def test_sitemap_keeps_only_recent_events():
    urls = sitemap_urls(SITEMAP, TODAY)
    assert PLANTAS_URL in urls and CUSTODIA_URL in urls
    assert not any("jazz-festival" in u or "trujillo" in u for u in urls)  # eventos de 2024 y 2025
    assert not any("/museos/" in u or "/pieza/" in u or "recorridos" in u or u.endswith("/listings/") for u in urls)
    assert len(urls) == 7


def test_run_reads_recent_pages_and_skips_unchanged():
    title, lines = sample("museosrd_plantas_endemicas.txt")
    page = f"<html><body><h1>{title}</h1>" + "".join(f"<p>{ln}</p>" for ln in lines[10:]) + "</body></html>"
    sitemap = f"<urlset><url><loc>{PLANTAS_URL}</loc><lastmod>2026-11-24T17:50:50+00:00</lastmod></url></urlset>"

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /wp-content/plugins/\n")
        return httpx.Response(200, text=sitemap if req.url.path.endswith(".xml") else page)

    db = DB(":memory:")
    f = Fetcher(transport=httpx.MockTransport(handler), sleep=lambda s: None, clock=lambda: 0.0)
    evs = MuseosRD(f, db, TODAY, "2026-11-24T12:00:00+00:00", log=lambda *_: None).run()
    assert [e.url for e in evs] == [PLANTAS_URL]
    assert MuseosRD(f, db, TODAY, "2026-11-25T12:00:00+00:00", log=lambda *_: None).run() == []


def test_registered():
    assert SOURCES["museosrd"] is MuseosRD
