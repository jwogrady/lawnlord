"""Odyssey provider adapter: parse the four-JSON export into the case model."""

import lawnlord as main


def test_identity_combines_summary_and_history(ody_intake):
    model = main.parse_odyssey(ody_intake)
    ident = model.identity
    assert ident.case_number == "99-00-12345"
    # case-history wins where both have a value.
    assert ident.title == "Acme Association v. John Doe"
    assert ident.court == "1st Judicial District Court, Test County, TX"
    assert ident.judicial_officer == "Justice, Jane"
    assert ident.date_filed == "2025-01-02"
    assert ident.disposition_type == "Summary Judgment"
    assert ident.disposition_date == "2025-06-01"


def test_parties_from_history_with_attorneys(ody_intake):
    model = main.parse_odyssey(ody_intake)
    assert len(model.parties) == 2
    plaintiff, defendant = model.parties
    assert plaintiff.role == "Plaintiff"
    assert len(plaintiff.attorneys) == 1
    assert plaintiff.attorneys[0].name == "Pat Counsel"
    assert defendant.representation == "Pro Se"


def test_events_are_phase_tagged_timeline(ody_intake):
    model = main.parse_odyssey(ody_intake)
    assert len(model.events) == 3
    assert [e.phase for e in model.events] == [
        "Pleadings & Service",
        "Summary Judgment",
        "Judgment & Disposition",
    ]
    assert model.events[0].files == ("filings/Petition.pdf",)


def test_documents_dedupe_by_file_path_and_sort(ody_intake):
    model = main.parse_odyssey(ody_intake)
    # 5 docket rows across the three lists, one duplicate -> 4 unique documents.
    paths = [d.intake_path for d in model.documents]
    assert paths == sorted(paths)
    assert paths == [
        "filings/Citation.pdf",
        "filings/Final_Judgment.pdf",
        "filings/Motion.pdf",
        "filings/Petition.pdf",
    ]
    final = next(d for d in model.documents if d.filename == "Final_Judgment.pdf")
    assert final.title == "Final Judgment"
    assert final.declared_page_count == 4


def test_parse_is_deterministic(ody_intake):
    assert main.parse_odyssey(ody_intake) == main.parse_odyssey(ody_intake)


def test_provider_selector_falls_back_to_odyssey(ody_intake):
    # Unknown provider name still parses an Odyssey-shaped folder.
    assert main.parse_provider("ody", ody_intake) == main.parse_odyssey(ody_intake)
    assert main.parse_provider("mystery", ody_intake) == main.parse_odyssey(ody_intake)


def test_combo_provider_registered():
    # `combo` (the reconciled best-of-both intake, the recommended source of
    # truth) is registered as the merge adapter, not the bare Odyssey adapter.
    assert main.PROVIDERS["combo"] is main.parse_combo


def test_combo_degrades_to_odyssey_without_meta(ody_intake):
    # An Odyssey folder with no meta.json / no financials parses identically
    # to parse_odyssey (the merge adds nothing it doesn't have).
    assert main.parse_combo(ody_intake) == main.parse_odyssey(ody_intake)


def test_combo_merges_research_meta(combo_intake):
    model = main.parse_combo(combo_intake)
    # Base Odyssey data is preserved.
    assert model.identity.case_number == "99-00-12345"
    assert {d.filename for d in model.documents} >= {"Final_Judgment.pdf", "Petition.pdf"}

    # Attorney bar number merged from meta.json onto the matching party/attorney.
    plaintiff = next(p for p in model.parties if p.role == "Plaintiff")
    counsel = next(a for a in plaintiff.attorneys if a.name == "Pat Counsel")
    assert counsel.number == "24000001"

    # Hearings table (with result) comes from meta.json.
    assert len(model.hearings) == 1
    assert model.hearings[0].result == "Canceled - Case Disposed"

    # Financial summary lifted from the Odyssey financialInformation block.
    assert model.financials is not None
    assert model.financials.total_assessment == "366"
    assert model.financials.balance_due == "0"


def test_combo_docket_carries_comments_and_links_files(combo_intake):
    model = main.parse_combo(combo_intake)
    # All meta.json event rows become docket entries, including the pure
    # docket entry with no document.
    assert len(model.docket) == 2
    granted = next(d for d in model.docket if "granted" in d.comment)
    assert granted.documents[0].declared_page_count == 4
    # The docket document name resolved back to the source PDF.
    assert granted.documents[0].intake_path == "filings/Final_Judgment.pdf"
    no_doc = next(d for d in model.docket if not d.documents)
    assert "submission" in no_doc.comment


def test_missing_files_are_tolerated(tmp_path):
    empty = tmp_path / "ody"
    empty.mkdir()
    model = main.parse_odyssey(empty)
    assert model.identity.case_number == ""
    assert model.parties == ()
    assert model.events == ()
    assert model.documents == ()


def test_case_slug_from_number():
    assert main.case_slug("25-09-14566") == "25-09-14566"
    assert main.case_slug("") == "case"


def test_malformed_inputs_do_not_crash(tmp_path):
    """Imperfect provider exports degrade gracefully, never raise: non-object
    top-level JSON, invalid JSON, and non-dict elements are all skipped."""
    import json

    intake = tmp_path / "ody"
    intake.mkdir()
    # top-level JSON that is a list / null / invalid, plus non-dict elements.
    (intake / "case-summary.json").write_text("[1, 2, 3]", encoding="utf-8")
    (intake / "register-of-actions.json").write_text("not json at all", encoding="utf-8")
    (intake / "case-history.json").write_text(
        json.dumps(
            {
                "caseNumber": "1-2-3",
                "parties": ["a bare string", {"role": "Plaintiff", "name": "OK"}],
                "timeline": [None, {"event": "X", "files": None}],
            }
        ),
        encoding="utf-8",
    )
    (intake / "filings.json").write_text(
        json.dumps({"otherEventsOnThisCase": ["bare", {"file": "filings/A.pdf"}]}),
        encoding="utf-8",
    )

    model = main.parse_odyssey(intake)
    assert model.identity.case_number == "1-2-3"
    assert [p.name for p in model.parties] == ["OK"]  # bare string skipped
    assert [e.event for e in model.events] == ["X"]  # None entry skipped
    assert model.events[0].files == ()  # files: null tolerated
    assert [d.filename for d in model.documents] == ["A.pdf"]  # bare row skipped
