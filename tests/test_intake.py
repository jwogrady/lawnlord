"""Characterization tests for the intake-folder contract (intake.py)."""

import pytest

import lawnlord as main
from lawnlord.intake import load_intake, resolve_packet, scaffold


# ---------------------------------------------------------------------------
# load_intake
# ---------------------------------------------------------------------------


def test_load_intake_defaults(tmp_path):
    intake = load_intake(tmp_path)
    assert intake.intake_dir == (tmp_path / "intake").resolve()
    assert intake.corpus_dir == (tmp_path / "corpus").resolve()
    assert intake.manual_boundaries_path.name == "bundle-boundaries.json"
    assert intake.curation_path.name == "corpus-curation.json"
    assert intake.generated_boundaries_path.name == "bundle-boundaries.generated.json"


def test_load_intake_honors_config(tmp_path):
    (tmp_path / "lawnlord.toml").write_text(
        '[lawnlord]\nintake = "src/filings"\ncorpus = "dist/corpus"\n', encoding="utf-8"
    )
    intake = load_intake(tmp_path)
    assert intake.intake_dir == (tmp_path / "src" / "filings").resolve()
    assert intake.corpus_dir == (tmp_path / "dist" / "corpus").resolve()


def test_load_intake_bad_config_falls_back_to_defaults(tmp_path):
    (tmp_path / "lawnlord.toml").write_text("this is not valid toml = = =", encoding="utf-8")
    intake = load_intake(tmp_path)
    assert intake.intake_dir == (tmp_path / "intake").resolve()


# ---------------------------------------------------------------------------
# resolve_packet
# ---------------------------------------------------------------------------


def test_resolve_packet_single_zip(tmp_path):
    intake = load_intake(tmp_path)
    intake.intake_dir.mkdir(parents=True)
    packet = intake.intake_dir / "case.zip"
    packet.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal empty-zip-ish bytes
    assert resolve_packet(intake) == packet.resolve()


def test_resolve_packet_none_exits(tmp_path):
    intake = load_intake(tmp_path)
    intake.intake_dir.mkdir(parents=True)
    with pytest.raises(SystemExit):
        resolve_packet(intake)


def test_resolve_packet_multiple_exits(tmp_path):
    intake = load_intake(tmp_path)
    intake.intake_dir.mkdir(parents=True)
    (intake.intake_dir / "a.zip").write_bytes(b"x")
    (intake.intake_dir / "b.zip").write_bytes(b"x")
    with pytest.raises(SystemExit):
        resolve_packet(intake)


def test_resolve_packet_explicit_wins(tmp_path):
    intake = load_intake(tmp_path)
    intake.intake_dir.mkdir(parents=True)
    (intake.intake_dir / "in-intake.zip").write_bytes(b"x")
    explicit = tmp_path / "elsewhere.zip"
    explicit.write_bytes(b"x")
    assert resolve_packet(intake, explicit) == explicit.resolve()


def test_resolve_packet_explicit_missing_raises(tmp_path):
    intake = load_intake(tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_packet(intake, tmp_path / "nope.zip")


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


def test_scaffold_creates_intake_config_and_readme(tmp_path):
    touched = scaffold(tmp_path)
    assert (tmp_path / "intake").is_dir()
    assert (tmp_path / "lawnlord.toml").exists()
    assert (tmp_path / "intake" / "README.md").exists()
    assert (tmp_path / "lawnlord.toml") in touched


def test_scaffold_is_idempotent_without_force(tmp_path):
    scaffold(tmp_path)
    # A second run touches nothing (files already present).
    assert scaffold(tmp_path) == []


def test_scaffold_force_overwrites_config(tmp_path):
    scaffold(tmp_path)
    (tmp_path / "lawnlord.toml").write_text("edited", encoding="utf-8")
    scaffold(tmp_path, force=True)
    assert "[lawnlord]" in (tmp_path / "lawnlord.toml").read_text(encoding="utf-8")


# Re-exported on the package surface.
def test_intake_symbols_exported():
    assert hasattr(main, "Intake")
    assert hasattr(main, "load_intake")
    assert hasattr(main, "resolve_packet")
    assert hasattr(main, "scaffold")
