"""Utilidades de HTML: texto visible por líneas, etiquetas "Campo: valor" y huella del contenido."""

from __future__ import annotations

import hashlib
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

_DROP = "script, style, noscript, svg, template"


def parse(html: str) -> HTMLParser:
    tree = HTMLParser(html)
    for n in tree.css(_DROP):
        n.decompose()
    return tree


def text_lines(tree: HTMLParser) -> list[str]:
    node = tree.body or tree.root
    if node is None:
        return []
    raw = node.text(separator="\n", strip=True)
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def fingerprint(html: str) -> str:
    """Huella del texto visible: ignora tokens CSRF, scripts y marcas de tiempo del HTML."""
    return hashlib.sha1("\n".join(text_lines(parse(html))).encode()).hexdigest()


def label_value(lines: list[str], *labels: str) -> str | None:
    """Valor de 'Etiqueta: valor', o de la línea siguiente cuando la etiqueta está sola."""
    for i, line in enumerate(lines):
        for lab in labels:
            m = re.match(rf"^{re.escape(lab)}\s*:\s*(.*)$", line, re.I)
            if m:
                v = m.group(1).strip()
                if v:
                    return v
                if i + 1 < len(lines):
                    return lines[i + 1]
            elif line.strip().lower() == lab.lower() and i + 1 < len(lines):
                return lines[i + 1]
    return None
