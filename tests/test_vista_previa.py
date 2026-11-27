"""La vista previa al compartir (WhatsApp, Facebook, X) depende de las etiquetas Open Graph de docs/index.html.

Si og:url o og:image apuntan a otro dominio que redirige (como pasó con edwingenao.github.io), WhatsApp
no arma la tarjeta. Estas pruebas fijan que todo apunte a https://agendasdq.com/ y que la imagen sea liviana.
"""
import re
import struct
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
SITIO = "https://agendasdq.com/"
HTML = (DOCS / "index.html").read_text(encoding="utf-8")
HEAD = HTML.split("</head>", 1)[0]


def _meta(clave):
    m = re.search(rf'<meta (?:property|name)="{re.escape(clave)}" content="([^"]*)"', HEAD)
    return m.group(1) if m else None


def test_no_queda_el_dominio_viejo():
    assert "github.io" not in HTML


def test_urls_de_la_vista_previa_usan_el_dominio():
    canonical = re.search(r'<link rel="canonical" href="([^"]*)"', HEAD).group(1)
    assert canonical == SITIO
    assert _meta("og:url") == SITIO
    for clave in ("og:image", "og:image:secure_url", "twitter:image"):
        assert _meta(clave) == SITIO + "og.png", clave


def test_etiquetas_basicas_presentes():
    for clave in ("og:title", "og:description", "og:type", "og:image:alt",
                  "twitter:card", "twitter:title", "twitter:description"):
        assert _meta(clave), clave


def test_etiquetas_og_antes_del_css():
    # Algunos rastreadores solo leen el principio de la página.
    assert HEAD.index('property="og:image"') < HEAD.index("<style")


def test_imagen_liviana_y_del_tamano_declarado():
    png = (DOCS / "og.png").read_bytes()
    assert len(png) < 300_000, "WhatsApp descarta imágenes pesadas"
    ancho, alto = struct.unpack(">II", png[16:24])
    assert (ancho, alto) == (int(_meta("og:image:width")), int(_meta("og:image:height"))) == (1200, 630)


def test_el_cname_sigue_en_su_sitio():
    assert (DOCS / "CNAME").read_text().strip() == "agendasdq.com"
