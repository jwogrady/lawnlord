"""Configurable intake root: provider commands resolve either an explicit path
or a bare provider name, under LAWNLORD_INTAKE / lawnlord.toml / ./intake — so
the case data can live in a separate repo or local in the project."""

import argparse
from pathlib import Path

from lawnlord import cli


def _provider(root: Path, name: str) -> Path:
    (root / name / "filings").mkdir(parents=True)
    return root / name


def test_explicit_path_is_used_as_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = _provider(tmp_path / "anywhere", "combo")
    assert cli._resolve_intake(str(d)) == d.resolve()


def test_env_var_root_resolves_a_bare_provider_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "gcp-hoa-case" / "intake"  # the "separate repo" layout
    _provider(root, "combo")
    monkeypatch.setenv("LAWNLORD_INTAKE", str(root))
    assert cli._resolve_intake("combo") == (root / "combo").resolve()


def test_toml_root_resolves_a_bare_provider_name(tmp_path, monkeypatch):
    monkeypatch.delenv("LAWNLORD_INTAKE", raising=False)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "lawnlord.toml").write_text(
        '[lawnlord]\nintake = "../data/intake"\n', encoding="utf-8"
    )
    _provider(tmp_path / "data" / "intake", "ody")
    monkeypatch.chdir(project)
    assert cli._resolve_intake("ody") == (tmp_path / "data" / "intake" / "ody").resolve()


def test_local_intake_is_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("LAWNLORD_INTAKE", raising=False)
    _provider(tmp_path / "intake", "combo")
    monkeypatch.chdir(tmp_path)
    assert cli._resolve_intake("combo") == (tmp_path / "intake" / "combo").resolve()


def test_every_subcommand_maps_to_a_callable_handler():
    """Lock in the command->handler dispatch seam: every subcommand the parser
    accepts has exactly one callable handler in COMMANDS, and vice versa."""
    parser = cli.build_parser()
    # Pull the registered subcommand names straight off the subparsers action.
    subparsers = next(
        a for a in parser._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    command_names = set(subparsers.choices)

    expected = {
        "start", "import", "export-actual", "export-exploded", "export-metrics",
        "export-regions", "explode", "regions", "transcribe", "measure",
    }
    assert command_names == expected
    assert set(cli.COMMANDS) == command_names
    for name, handler in cli.COMMANDS.items():
        assert callable(handler), name


def test_main_dispatches_to_the_registered_handler(monkeypatch):
    """_main parses args, looks up the handler, and invokes it with the
    Namespace — drive a representative command end-to-end through the seam."""
    seen = {}

    def fake_start(args):
        seen["command"] = args.command
        seen["force"] = args.force

    monkeypatch.setitem(cli.COMMANDS, "start", fake_start)
    cli._main(["start", "--force", "some/root"])
    assert seen == {"command": "start", "force": True}
