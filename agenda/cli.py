"""CLI:  python -m agenda run | inspect URL | export | sources"""

from __future__ import annotations

import argparse
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from agenda.db import DB
from agenda.export import export_json
from agenda.htmlutil import parse, text_lines
from agenda.http import Disallowed, Fetcher
from agenda.sources import SOURCES


def _today(args) -> date:
    return date.fromisoformat(args.today) if getattr(args, "today", None) else date.today()


def cmd_run(args) -> int:
    today = _today(args)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = DB(args.db)
    fetcher = Fetcher()
    wanted = args.source or list(SOURCES)
    unknown = [s for s in wanted if s not in SOURCES]
    if unknown:
        print(f"Fuente(s) desconocida(s): {', '.join(unknown)}. Disponibles: {', '.join(SOURCES)}")
        return 2
    failures = 0
    try:
        for sid in wanted:
            src = SOURCES[sid](fetcher, db, today, now, max_details=args.max_details)
            print(f"== {src.name} ({sid})")
            try:
                events = src.run()
            except Disallowed as e:
                print(f"   omitida: {e}")
                failures += 1
                continue
            except Exception as e:  # una fuente rota no debe tumbar a las demás
                print(f"   ERROR: {type(e).__name__}: {e}")
                failures += 1
                continue
            counts = {"new": 0, "updated": 0, "same": 0}
            for ev in events:
                counts[db.upsert_event(ev, now)] += 1
            print(f"   {len(events)} eventos leídos: {counts['new']} nuevos, {counts['updated']} actualizados, "
                  f"{counts['same']} sin cambios")
    finally:
        fetcher.close()
    print()
    n = export_json(db, args.out, today, log=print)
    review = db.review_queue(today)
    print(f"\nExportados {n} eventos próximos a {args.out}")
    if review:
        print(f"{len(review)} evento(s) necesitan revisión (fecha o precio dudosos):")
        for p in review[:10]:
            print(f"   - {p['title']}  {p['url']}")
    return 1 if failures == len(wanted) else 0


def cmd_inspect(args) -> int:
    """Descarga una URL (respetando robots.txt) y guarda el HTML y su texto, para ajustar selectores."""
    fetcher = Fetcher()
    try:
        r = fetcher.get(args.url, delay=args.delay)
    except Disallowed as e:
        print(f"No se pudo descargar (robots.txt o red): {e}")
        return 2
    finally:
        fetcher.close()
    p = urlparse(args.url)
    slug = re.sub(r"[^a-z0-9]+", "_", (p.netloc + p.path).lower()).strip("_")[:80]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{slug}.html").write_text(r.text, encoding="utf-8")
    lines = text_lines(parse(r.text))
    (out / f"{slug}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"HTTP {r.status_code} · {len(r.text)} bytes · {len(lines)} líneas de texto")
    print(f"Guardado en {out / (slug + '.html')} y {out / (slug + '.txt')}")
    return 0


def cmd_export(args) -> int:
    n = export_json(DB(args.db), args.out, _today(args), log=print)
    print(f"Exportados {n} eventos a {args.out}")
    return 0


def cmd_sources(_args) -> int:
    for sid, cls in SOURCES.items():
        print(f"{sid:16} {cls.name}  (espera {cls.delay:g}s entre peticiones)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agenda", description="Agenda cultural de Santo Domingo")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--db", default=os.environ.get("AGENDA_DB", "data/agenda.db"))
        p.add_argument("--out", default="docs/events.json")
        p.add_argument("--today", help="YYYY-MM-DD (para pruebas)")

    p = sub.add_parser("run", help="leer fuentes, guardar y exportar")
    common(p)
    p.add_argument("--source", action="append", help="id de fuente (repetible); por defecto, todas")
    p.add_argument("--max-details", type=int, default=None, help="máx. páginas de detalle por fuente")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("inspect", help="guardar el HTML de una URL para ajustar selectores")
    p.add_argument("url")
    p.add_argument("--out", default="inspect")
    p.add_argument("--delay", type=float, default=3.0)
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("export", help="exportar events.json desde la base")
    common(p)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("sources", help="listar fuentes")
    p.set_defaults(fn=cmd_sources)

    args = ap.parse_args(argv)
    return args.fn(args)
