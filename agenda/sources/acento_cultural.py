"""Acento Cultural (acento.com.do): agenda semanal de arte y cultura, en texto libre, leída con IA.

Verificado el 7 oct 2026 desde la PC:
  - robots.txt no prohíbe nada (`User-agent: *` sin Disallow) y anuncia sitemaps.
  - Cada semana sale una nota /cultura/acento-cultural-N-ID.html ("17 al 23 de septiembre de 2026"), con secciones
    por ciudad (SANTO DOMINGO, BANÍ, SANTIAGO) y entradas como "🎭 CHICAGO: EL MUSICAL / Teatro Nacional · Sala
    Carlos Piantini / 18, 19 y 20 de septiembre · 8:30 p. m. / (Domingo 20: 7:00 p. m.)". También trae reseñas de
    libros y encuentros ya celebrados, que no son eventos.
  - La nota más reciente se encuentra en los sitemaps: primero sitemaps-daily.xml (artículos recientes) y, si no
    está, el último /sitemaps/acento-N.txt de sitemaps-index.xml (todas las URL del sitio, ~800 KB).
  - Ese día la última era la 61 (17 de septiembre): llevaba tres semanas sin una nueva.
  - La página trae el correo personal del autor: la muestra en samples/ va sin él.

Cómo se lee: el texto de <article> va a `llm.extract_events` (salida con esquema JSON). Lo que devuelve el modelo
se contrasta con el texto antes de publicarlo: solo Santo Domingo, sin fechas pasadas, hora válida, precio solo si el
monto aparece en la nota y gratis solo si la nota lo dice. Todo sale con needs_review=True. Sin AGENDA_LLM=1 y
ANTHROPIC_API_KEY la fuente no publica nada (y lo dice en la corrida).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta

from agenda import llm
from agenda.htmlutil import parse
from agenda.models import Event, guess_kids, normalize_category, zone_for
from agenda.sources.base import Source

SITE = "https://acento.com.do"
DAILY_SITEMAP = SITE + "/sitemaps/sitemaps-daily.xml"
INDEX_SITEMAP = SITE + "/sitemaps/sitemaps-index.xml"
NOTE_URL = re.compile(r"https://acento\.com\.do/cultura/acento-cultural-(\d+)-\d+\.html")
MAX_DESCRIPTION = 280
CATEGORIES = {"Música", "Teatro", "Danza", "Cine", "Arte", "Cultura"}
SDQ_CITIES = {"santo domingo", "distrito nacional", "santo domingo este", "santo domingo oeste",
              "santo domingo norte", "santo domingo de guzman"}
FREE_WORDS = re.compile(r"\b(gratis|gratuit[oa]s?|entrada libre|libre acceso)\b", re.I)
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(s)).strip("-")[:60]


def latest_note(urls: list[str]) -> str | None:
    """La URL de la nota con el número más alto."""
    best = max(((int(m.group(1)), m.group(0)) for u in urls if (m := NOTE_URL.search(u))), default=None)
    return best[1] if best else None


def article_text(html: str) -> tuple[str, str, str]:
    """(texto del artículo, titular, fecha de publicación ISO o "")."""
    tree = parse(html)
    node = tree.css_first("article") or tree.body
    text = re.sub(r"\n{2,}", "\n", node.text(separator="\n")) if node else ""
    text = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
    text = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "", text)  # el correo del autor no se manda a la API
    headline, published = "", ""
    # parse() quita los <script>: el JSON-LD se lee del HTML crudo.
    for raw in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "NewsArticle":
                headline = item.get("headline") or ""
                published = (item.get("datePublished") or "")[:10]
    return text, headline, published


def _amount_in_text(n: int | None, text: str) -> bool:
    """El monto aparece en la nota (1200, 1,200 o 1.200)."""
    if not isinstance(n, int) or n <= 0:
        return False
    plain = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", text)
    return re.search(rf"(?<![\d.,]){n}(?![\d])", plain) is not None


def _find(title: str, t: str) -> tuple[int, int] | None:
    """(inicio, fin) del título dentro del texto ya normalizado, o None."""
    n = _norm(title)
    if not n:
        return None
    pos = t.find(n)
    if pos >= 0:
        return pos, pos + len(n)
    words = [w for w in re.findall(r"\w+", n) if len(w) > 3][:3]  # el modelo a veces acorta o corrige el título
    if not words:
        return None
    m = re.search(r"\b" + r"\W+(?:\w+\W+){0,3}?".join(map(re.escape, words)), t)
    return (m.start(), m.end()) if m else None


def event_block(title: str, text: str, others: list[str] = (), size: int = 450) -> str | None:
    """El trozo de la nota que habla de ese evento: desde su título hasta la siguiente entrada (un emoji o el título de
    otro evento), como mucho `size` caracteres. None si el título no aparece en la nota."""
    t = _norm(text)
    found = _find(title, t)
    if not found:
        return None
    start, end = found
    stop = end + size
    emoji = re.search(r"[\U0001F300-\U0001FAFF]", t[end:stop])
    if emoji:
        stop = end + emoji.start()
    for other in others:
        f = _find(other, t)
        if f and end <= f[0] < stop:
            stop = f[0]
    return t[start:stop]


def build_events(items: list, note_url: str, text: str, today: date) -> list[Event]:
    """Pasa lo que propuso el modelo por las reglas del producto. Nada que no esté en el texto llega al sitio.

    Precio y gratuidad se comprueban en el bloque de cada evento, no en toda la nota: la nota casi siempre dice
    "gratuita" en algún lado, y eso no hace gratis a los demás eventos."""
    out: list[Event] = []
    seen: set[str] = set()
    horizon = today + timedelta(days=400)
    titles = [str(i.get("title") or "") for i in items or [] if isinstance(i, dict)]
    for it in items or []:
        if not isinstance(it, dict):
            continue
        title = re.sub(r"\s+", " ", str(it.get("title") or "")).strip()
        if not title or _norm(it.get("city") or "") not in SDQ_CITIES:
            continue
        dates = []
        for d in it.get("dates") or []:
            try:
                dates.append(date.fromisoformat(str(d)))
            except ValueError:
                continue
        dates = sorted(d for d in set(dates) if d <= horizon)
        if not dates or dates[-1] < today:
            continue
        if dates[0] < today:  # en curso: desde hoy
            dates = [today] + [d for d in dates if d > today]
        start_time = it.get("start_time") or ""
        start_time = start_time if _TIME.match(start_time) else None

        block = event_block(title, text, others=[o for o in titles if o != title]) or ""
        pmin, pmax = it.get("price_min"), it.get("price_max")
        pmin = pmin if _amount_in_text(pmin, block) else None
        pmax = pmax if _amount_in_text(pmax, block) and pmin is not None and pmax > pmin else None
        if it.get("is_free") is True and FREE_WORDS.search(block) and pmin is None:
            is_free, pmin = True, 0
        elif pmin is not None:
            is_free = False
        else:
            is_free = None

        venue = re.sub(r"\s+", " ", str(it.get("venue") or "")).strip()
        category = it.get("category") if it.get("category") in CATEGORIES else normalize_category(title)
        desc = re.sub(r"\s+", " ", str(it.get("description") or "")).strip()
        if len(desc) > MAX_DESCRIPTION:
            desc = desc[: MAX_DESCRIPTION - 1].rstrip() + "…"
        url = f"{note_url}#{_slug(title)}-{dates[0].isoformat()}"
        if url in seen:
            continue
        seen.add(url)
        out.append(Event(
            source="acento_cultural",
            source_name="Acento Cultural",
            url=url,
            title=title,
            dates=[d.isoformat() for d in dates],
            start_time=start_time,
            venue=venue,
            zone=zone_for(venue),
            category=category,
            is_free=is_free,
            price_min=pmin,
            price_max=pmax,
            kids=guess_kids(title, desc),
            description=desc,
            needs_review=True,
        ))
    return out


class AcentoCultural(Source):
    id = "acento_cultural"
    name = "Acento Cultural"
    delay = 5.0
    extract = staticmethod(llm.extract_events)  # las pruebas lo cambian por uno falso

    def _find_note(self) -> str | None:
        xml = self.fetcher.get(DAILY_SITEMAP, delay=self.delay).text
        note = latest_note(re.findall(r"<loc>([^<]+)</loc>", xml))
        if note:
            return note
        index = self.fetcher.get(INDEX_SITEMAP, delay=self.delay).text
        parts = re.findall(r"<loc>([^<]+\.txt)</loc>", index)
        if not parts:
            return None
        last = max(parts, key=lambda u: int(re.search(r"(\d+)\.txt$", u).group(1)) if re.search(r"(\d+)\.txt$", u) else -1)
        return latest_note(self.fetcher.get(last, delay=self.delay).text.split())

    def run(self) -> list[Event]:
        if not llm.available():
            self.log(f"[{self.id}] extracción con IA desactivada (falta AGENDA_LLM=1 o ANTHROPIC_API_KEY): no se lee.")
            return []
        note = self._find_note()
        if not note:
            self.log(f"[{self.id}] no encontré ninguna nota acento-cultural en los sitemaps.")
            return []
        html, fp, changed = self.fetch_page(note)
        if not changed:
            self.log(f"[{self.id}] {note} no cambió desde la última lectura.")
            return []
        text, headline, published = article_text(html)
        items = self.extract(text, note, self.today, headline)
        if items is None:
            self.log(f"[{self.id}] la extracción no devolvió un resultado usable para {note}.")
            return []
        events = build_events(items, note, text, self.today)
        self.log(f"[{self.id}] {note} (publicada {published or '?'}): el modelo propuso {len(items)}, "
                 f"{len(events)} pasan las reglas (Santo Domingo, sin fechas pasadas).")
        self.db.record_page(note, fp, self.now)
        return events
