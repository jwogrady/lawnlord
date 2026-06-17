"""Ingest: docket metadata from a Case into the DuckDB index."""

import lawnlord as main

GEN = "2026-06-16T00:00:00Z"


def _fresh_db(tmp_path):
    con = main.open_case_db(tmp_path / "lawnlord.duckdb")
    main.apply_schema(con)
    return con


def test_ingest_counts(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    con = _fresh_db(tmp_path)
    stats = main.ingest_case(con, case, GEN)
    assert stats["cases"] == 1
    assert stats["parties"] == 2
    assert stats["events"] == 3
    assert stats["images"] == 4
    assert stats["skipped_images"] == []
    # Row counts in the DB match.
    assert con.execute("SELECT count(*) FROM cases").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM parties").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM events").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM images").fetchone()[0] == 4


def test_ingest_case_row_from_curated_identity(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    con = _fresh_db(tmp_path)
    main.ingest_case(con, case, GEN)
    row = con.execute(
        "SELECT id, judicial_officer, disposition_type, created_at FROM cases"
    ).fetchone()
    assert row[0] == "99-00-12345"
    assert row[1] == "Justice, Jane"
    assert row[2] == "Summary Judgment"
    assert row[3] == GEN  # deterministic timestamp, not wall-clock


def test_image_ids_match_exploder_scheme(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    con = _fresh_db(tmp_path)
    main.ingest_case(con, case, GEN)
    for image_id, sha in con.execute("SELECT id, sha256_hash FROM images").fetchall():
        assert image_id == f"doc_{sha[:16]}"


def test_image_events_link_many_to_many(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    con = _fresh_db(tmp_path)
    main.ingest_case(con, case, GEN)
    # Each of the 3 timeline events references exactly one (present) image.
    assert con.execute("SELECT count(*) FROM image_events").fetchone()[0] == 3
    # The Motion image links to the MSJ event.
    linked = con.execute(
        """
        SELECT e.event_type FROM image_events ie
        JOIN images i ON i.id = ie.image_id
        JOIN events e ON e.id = ie.event_id
        WHERE i.filename = 'Motion.pdf'
        """
    ).fetchone()
    assert linked[0] == "Motion for Summary Judgment"


def test_ingest_is_deterministic_and_rebuilds(ody_intake, tmp_path):
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")

    def dump(con):
        out = {}
        for t in ("cases", "parties", "events", "images", "image_events"):
            out[t] = con.execute(f"SELECT * FROM {t} ORDER BY ALL").fetchall()
        return out

    con = _fresh_db(tmp_path)
    main.ingest_case(con, case, GEN)
    first = dump(con)
    # Re-ingest into the same DB: drop-and-rebuild yields identical rows.
    main.ingest_case(con, case, GEN)
    assert dump(con) == first
    # A fresh DB ingested the same way matches too.
    con2 = _fresh_db(tmp_path / "again")
    main.ingest_case(con2, case, GEN)
    assert dump(con2) == first


def test_event_ids_unique_when_many_share_date_and_type(tmp_path):
    """Three events with the same (date, event) must not collide (PK violation)
    — realistic dockets log the same routine event several times in a day."""
    same = [
        main.Event(date="2025-09-05", phase="Pleadings & Service",
                   event="Request for Service", party=p)
        for p in ("Defendant A", "Defendant B", "Defendant C")
    ]
    model = main.CaseModel(
        provider="ody",
        identity=main.CaseIdentity(case_number="77-00-00001"),
        parties=(),
        events=tuple(same),
        documents=(),
    )
    case = main.Case(
        intake_dir=tmp_path, provider="ody", case_dir=tmp_path, model=model
    )
    con = _fresh_db(tmp_path)
    stats = main.ingest_case(con, case, GEN)
    assert stats["events"] == 3
    ids = [r[0] for r in con.execute("SELECT id FROM events").fetchall()]
    assert len(set(ids)) == 3  # all distinct, no collision


def test_missing_pdf_is_skipped_not_fabricated(ody_intake, tmp_path):
    (ody_intake / "filings" / "Motion.pdf").unlink()
    case = main.Case.from_intake(ody_intake, case_dir=tmp_path / "out")
    con = _fresh_db(tmp_path)
    stats = main.ingest_case(con, case, GEN)
    assert "filings/Motion.pdf" in stats["skipped_images"]
    assert stats["images"] == 3
    # No row with a missing/empty hash slipped in.
    assert con.execute(
        "SELECT count(*) FROM images WHERE sha256_hash IS NULL OR sha256_hash = ''"
    ).fetchone()[0] == 0
