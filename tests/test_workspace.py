"""Case workspace: resolve intake input + output paths with no REPO_ROOT."""

from pathlib import Path

import lawnlord as main


def test_from_intake_resolves_model(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    assert case.provider == "ody"
    assert case.case_number == "99-00-12345"
    assert case.case_slug == "99-00-12345"  # from caseNumber, not the folder name
    assert len(case.parties) == 2
    assert len(case.events) == 3
    assert len(case.documents) == 4
    assert case.identity.judicial_officer == "Justice, Jane"


def test_intake_paths_point_into_provider_folder(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    assert case.case_summary_path == ody_intake / "case-summary.json"
    assert case.case_history_path == ody_intake / "case-history.json"
    assert case.register_of_actions_path == ody_intake / "register-of-actions.json"
    assert case.filings_json_path == ody_intake / "filings.json"
    assert case.filings_dir == ody_intake / "filings"


def test_output_paths_under_case_dir(ody_intake, tmp_path):
    out = tmp_path / "out"
    case = main.Case.from_intake(ody_intake, case_dir=out)
    assert case.case_dir == out.resolve()
    assert case.corpus_dir == out.resolve() / "extracted" / "corpus"
    assert case.duckdb_path == out.resolve() / "lawnlord.duckdb"
    assert case.case_json_path == out.resolve() / "manifests" / "case.json"
    assert len(case.output_dirs()) == len(main.OUTPUT_SUBDIRS) == 7
    # from_intake computes paths but creates nothing.
    assert not out.exists()


def test_case_dir_defaults_to_cwd(ody_intake):
    case = main.Case.from_intake(ody_intake)
    assert case.case_dir == Path.cwd()
