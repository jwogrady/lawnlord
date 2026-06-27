"""User-facing CLI dispatch coverage (#162).

Drives ``main()`` / ``main(argv)`` for each non-vision subcommand against a
hermetic ``tmp_path`` intake (reusing the ``test_reader._make_intake`` shape),
asserts exit behavior, that the export commands print parseable JSON on stdout,
and that known input errors surface a clean ``Error: …`` message with exit 1 (no
traceback). Also covers ``_intake_root`` / ``_resolve_intake`` precedence.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import lawnlord as main
from lawnlord import cli

from test_reader import _make_intake

_SRC = Path(__file__).resolve().parent.parent / "src"


def _import(tmp_path):
    """Materialize an intake and import it into a fresh case dir; return both."""
    intake = _make_intake(tmp_path)
    case_dir = tmp_path / "out"
    main.main(["import", str(intake), "--case-dir", str(case_dir)])
    return intake, case_dir


# --- subcommand dispatch ----------------------------------------------------


def test_start_scaffolds_intake(tmp_path):
    main.main(["start", str(tmp_path)])
    assert (tmp_path / "intake").is_dir()
    assert (tmp_path / "lawnlord.toml").is_file()
    # Idempotent: a second run reports nothing to create (no crash).
    main.main(["start", str(tmp_path)])


def test_import_builds_the_duckdb_mirror(tmp_path):
    _intake, case_dir = _import(tmp_path)
    assert (case_dir / "lawnlord.duckdb").is_file()


@pytest.mark.parametrize("subcommand", [
    "export-actual",
    "export-exploded",
    "export-metrics",
])
def test_export_commands_print_parseable_json(tmp_path, capsys, subcommand):
    _intake, case_dir = _import(tmp_path)
    capsys.readouterr()  # drain the import summary table off stdout
    main.main([subcommand, "--case-dir", str(case_dir)])
    out = capsys.readouterr().out
    # The export commands emit ONLY JSON on stdout so the viewer can parse it.
    payload = json.loads(out)
    assert isinstance(payload, (dict, list))


def test_export_regions_prints_parseable_json(tmp_path, capsys):
    # export-regions requires a --page; an unknown page id still yields JSON
    # (an empty regions payload), never a traceback.
    _intake, case_dir = _import(tmp_path)
    capsys.readouterr()  # drain the import summary table off stdout
    main.main(["export-regions", "--case-dir", str(case_dir), "--page", "nope"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)


def test_export_exploded_accepts_a_selector(tmp_path, capsys):
    _intake, case_dir = _import(tmp_path)
    capsys.readouterr()  # drain the import summary table off stdout
    main.main(["export-exploded", "--case-dir", str(case_dir), "--image", "missing"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, (dict, list))


def _import_renderable(tmp_path):
    """Import an intake whose filed PDF is a real (pypdf) renderable doc, so the
    explode/regions commands can run end-to-end through their CLI dispatch."""
    from pypdf import PdfWriter

    intake = _make_intake(tmp_path)
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with open(intake / "files" / "doc-1.pdf", "wb") as f:
        w.write(f)
    case_dir = tmp_path / "out"
    main.main(["import", str(intake), "--case-dir", str(case_dir)])
    return case_dir


def test_explode_runs_against_an_imported_case(tmp_path):
    case_dir = _import_renderable(tmp_path)
    main.main(["explode", "--case-dir", str(case_dir)])
    con = main.open_case_db(case_dir / "lawnlord.duckdb", read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    finally:
        con.close()


def test_regions_runs_against_an_imported_case(tmp_path):
    case_dir = _import_renderable(tmp_path)
    main.main(["regions", "--case-dir", str(case_dir)])


# --- error handling: clean message + exit 1, no traceback -------------------


def test_export_actual_missing_case_dir_exits_1(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main.main(["export-actual", "--case-dir", str(tmp_path / "nonexistent")])
    assert excinfo.value.code == 1
    # main() reports known input errors via the Rich console (stdout) as a clean
    # "Error: …" line and exits 1 — no traceback.
    assert "Error:" in capsys.readouterr().out


def test_import_missing_intake_exits_1(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main.main(["import", str(tmp_path / "no-such-intake"),
                   "--case-dir", str(tmp_path / "out")])
    assert excinfo.value.code == 1
    assert "Error:" in capsys.readouterr().out


def test_import_dir_without_data_json_exits_1(tmp_path, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(SystemExit) as excinfo:
        main.main(["import", str(bare), "--case-dir", str(tmp_path / "out")])
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Error:" in out
    assert "data.json" in out


# --- _intake_root / _resolve_intake precedence ------------------------------


def test_intake_root_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    monkeypatch.setenv("LAWNLORD_INTAKE", str(target))
    assert cli._intake_root() == target.resolve()


def test_intake_root_toml_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("LAWNLORD_INTAKE", raising=False)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    # Paths in lawnlord.toml are relative to the file's directory (the cwd).
    (project / "lawnlord.toml").write_text(
        '[lawnlord]\nintake = "../data/intake"\n', encoding="utf-8"
    )
    assert cli._intake_root() == (tmp_path / "data" / "intake").resolve()


def test_intake_root_default_is_local_intake(tmp_path, monkeypatch):
    monkeypatch.delenv("LAWNLORD_INTAKE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli._intake_root() == (tmp_path / "intake").resolve()


def test_resolve_intake_explicit_path_used_as_is(tmp_path, monkeypatch):
    monkeypatch.delenv("LAWNLORD_INTAKE", raising=False)
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "anywhere"
    d.mkdir()
    assert cli._resolve_intake(str(d)) == d.resolve()


def test_resolve_intake_bare_name_under_env_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "root"
    (root / "combo").mkdir(parents=True)
    monkeypatch.setenv("LAWNLORD_INTAKE", str(root))
    assert cli._resolve_intake("combo") == (root / "combo").resolve()


# --- python -m lawnlord (exercise __main__.py so it is no longer 0%) --------


def test_module_entry_point_help_runs(tmp_path):
    """`python -m lawnlord --help` exits 0 and prints usage, executing
    __main__.py's import + ``main()`` call path through the console script."""
    proc = subprocess.run(
        [sys.executable, "-m", "lawnlord", "--help"],
        capture_output=True, text=True, cwd=tmp_path,
        env={"PYTHONPATH": str(_SRC), "PATH": __import__("os").environ.get("PATH", "")},
    )
    assert proc.returncode == 0
    assert "lawnlord" in proc.stdout


def test_module_entry_runpy_invokes_main(monkeypatch):
    """Execute __main__.py in-process as ``__main__`` (so its line coverage is no
    longer 0%): the ``if __name__ == '__main__': main()`` guard fires and
    --help raises SystemExit(0)."""
    import runpy

    monkeypatch.setattr(sys, "argv", ["lawnlord", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("lawnlord.__main__", run_name="__main__")
    assert excinfo.value.code == 0


def test_module_entry_point_no_args_is_usage_error(tmp_path):
    """No subcommand is a usage error (argparse exit 2), still routed through
    __main__.py's entry path."""
    proc = subprocess.run(
        [sys.executable, "-m", "lawnlord"],
        capture_output=True, text=True, cwd=tmp_path,
        env={"PYTHONPATH": str(_SRC), "PATH": __import__("os").environ.get("PATH", "")},
    )
    assert proc.returncode == 2
    assert "command" in proc.stderr or "usage" in proc.stderr
