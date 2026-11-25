"""Aviso cuando una fuente falla: `agenda run` deja data/alerta.txt y el workflow lo convierte en una falla visible."""

from datetime import date

from agenda import cli
from agenda.http import Disallowed
from agenda.models import Event
from agenda.sources.base import Source

TODAY = date(2026, 11, 24)


def make(sid, behaviour):
    class S(Source):
        id = sid
        name = sid.upper()
        delay = 0

        def run(self):
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour

    return S


def ev(sid):
    return Event(source=sid, source_name=sid, url=f"https://x.test/{sid}", title="Algo", dates=["2026-12-01"], venue="Sala")


def run(tmp_path, monkeypatch, sources, argv_extra=()):
    monkeypatch.setattr(cli, "SOURCES", sources)
    monkeypatch.setenv("AGENDA_ALERT", str(tmp_path / "alerta.txt"))
    monkeypatch.setattr(cli, "Fetcher", lambda: type("F", (), {"close": lambda self: None})())
    args = ["run", "--db", str(tmp_path / "a.db"), "--out", str(tmp_path / "events.json"), "--today", "2026-11-24", *argv_extra]
    return cli.main(args)


def test_failing_source_writes_alert_but_keeps_others(tmp_path, monkeypatch, capsys):
    srcs = {"bueno": make("bueno", [ev("bueno")]), "roto": make("roto", RuntimeError("se cayó")),
            "bloqueado": make("bloqueado", Disallowed("403"))}
    assert run(tmp_path, monkeypatch, srcs) == 0  # no todas fallaron: se publica lo que hay
    text = (tmp_path / "alerta.txt").read_text(encoding="utf-8")
    assert "`roto`: RuntimeError: se cayó" in text and "`bloqueado`: omitida" in text and "bueno" not in text.split("(aviso)")[0]
    assert (tmp_path / "events.json").exists()
    assert "ALERTA: 2 fuente(s)" in capsys.readouterr().out


def test_no_failures_removes_old_alert(tmp_path, monkeypatch):
    (tmp_path / "alerta.txt").write_text("- `viejo`: algo\n", encoding="utf-8")
    assert run(tmp_path, monkeypatch, {"bueno": make("bueno", [ev("bueno")])}) == 0
    assert not (tmp_path / "alerta.txt").exists()


def test_empty_source_is_only_a_notice(tmp_path, monkeypatch, capsys):
    srcs = {"bueno": make("bueno", [ev("bueno")]), "vacio": make("vacio", [])}
    assert run(tmp_path, monkeypatch, srcs) == 0
    assert not (tmp_path / "alerta.txt").exists()  # sin errores no hay alerta; solo aviso en el log
    assert "AVISO: vacio no tiene eventos próximos" in capsys.readouterr().out


def test_notices_travel_with_a_real_alert(tmp_path, monkeypatch):
    srcs = {"roto": make("roto", RuntimeError("x")), "vacio": make("vacio", []), "bueno": make("bueno", [ev("bueno")])}
    run(tmp_path, monkeypatch, srcs)
    assert "(aviso) vacio no tiene eventos próximos" in (tmp_path / "alerta.txt").read_text(encoding="utf-8")


def test_all_sources_failing_keeps_exit_code_1(tmp_path, monkeypatch):
    assert run(tmp_path, monkeypatch, {"roto": make("roto", RuntimeError("x"))}) == 1
    assert (tmp_path / "alerta.txt").exists()
