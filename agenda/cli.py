"""CLI:  python -m agenda run | inspect URL | export | sources"""

from __future__ import annotations

import argparse
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from agenda.dates import today_sdq
from agenda.db import DB
from agenda.export import export_json
from agenda.htmlutil import parse, text_lines
from agenda.http import Disallowed, Fetcher
from agenda.sources import SOURCES


def _today(args) -> date:
    return date.fromisoformat(args.today) if getattr(args, "today", None) else today_sdq()


ALERT_FILE = "data/alerta.txt"


def write_alert(path: str | Path, problems: list[tuple[str, str]], notices: list[str]) -> None:
    """Deja en `path` la lista de fuentes que fallaron (el workflow la lee y avisa); sin fallas, borra el archivo."""
    path = Path(path)
    if not problems:
        path.unlink(missing_ok=True)
        return
    lines = [f"- `{sid}`: {msg}" for sid, msg in problems]
    lines += [f"- (aviso) {n}" for n in notices]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    problems: list[tuple[str, str]] = []
    try:
        for sid in wanted:
            src = SOURCES[sid](fetcher, db, today, now, max_details=args.max_details)
            print(f"== {src.name} ({sid})")
            try:
                events = src.run()
            except Disallowed as e:
                print(f"   omitida: {e}")
                failures += 1
                problems.append((sid, f"omitida: {e}"))
                continue
            except Exception as e:  # una fuente rota no debe tumbar a las demás
                print(f"   ERROR: {type(e).__name__}: {e}")
                failures += 1
                problems.append((sid, f"{type(e).__name__}: {e}"))
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
    # Fuentes sin ningún evento próximo en la base: puede ser normal (SIC, Casa de Teatro) o una fuente muerta.
    have = {ev.get("source") for ev in db.upcoming(today)}
    notices = [f"{sid} no tiene eventos próximos en la base" for sid in wanted if sid not in have]
    for notice in notices:
        print(f"AVISO: {notice}")
    write_alert(os.environ.get("AGENDA_ALERT", ALERT_FILE), problems, notices)
    if problems:
        print(f"ALERTA: {len(problems)} fuente(s) con problemas: {', '.join(sid for sid, _ in problems)}")
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
