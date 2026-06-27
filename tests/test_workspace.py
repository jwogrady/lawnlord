"""``Case.from_intake`` resolution coverage (#162).

A valid extracted intake resolves provider/case_dir/model (and case_dir defaults
to cwd); a non-existent dir and a dir lacking data.json each raise
FileNotFoundError with the documented message.
"""

import pytest

import lawnlord as main
from lawnlord.workspace import Case

from test_reader import _make_intake


def test_from_intake_resolves_provider_case_dir_and_model(tmp_path):
    intake = _make_intake(tmp_path)
    case_dir = tmp_path / "out"
    case = Case.from_intake(intake, case_dir=case_dir)
    assert case.provider == "rake"
    assert case.case_dir == case_dir.resolve()
    assert case.intake_dir == intake.resolve()
    assert case.case_number == "99-00-12345"
    assert case.duckdb_path == case_dir.resolve() / "lawnlord.duckdb"


def test_from_intake_defaults_case_dir_to_cwd(tmp_path, monkeypatch):
    intake = _make_intake(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    case = Case.from_intake(intake)
    assert case.case_dir == work.resolve()


def test_from_intake_missing_dir_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError, match="intake folder not found"):
        Case.from_intake(tmp_path / "does-not-exist")


def test_from_intake_dir_without_data_json_raises_filenotfound(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(FileNotFoundError, match="no data.json"):
        Case.from_intake(bare)


def test_from_intake_string_path_is_accepted(tmp_path):
    intake = _make_intake(tmp_path)
    case = Case.from_intake(str(intake), case_dir=str(tmp_path / "out"))
    assert isinstance(case, Case)
    assert case.files_dir == intake.resolve() / main.FILES_DIRNAME
