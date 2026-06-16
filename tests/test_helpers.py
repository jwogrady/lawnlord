"""Characterization tests for the pure helpers in main.py.

These pin the *current* observable behavior of the generator's building
blocks before any refactor. They are deliberately literal: if a refactor
changes one of these outputs, that is a behavior change a human must approve,
not a test to silently update.
"""

import lawnlord as main


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_sha256_bytes_known_empty():
    # SHA-256 of the empty byte string is a fixed, well-known constant.
    assert main.sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_bytes_is_stable_and_hex():
    digest = main.sha256_bytes(b"hoa-case")
    assert digest == main.sha256_bytes(b"hoa-case")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_sha256_file_matches_bytes(tmp_path):
    p = tmp_path / "blob.bin"
    payload = b"court record packet"
    p.write_bytes(payload)
    assert main.sha256_file(p) == main.sha256_bytes(payload)


# ---------------------------------------------------------------------------
# Zip-entry safety
# ---------------------------------------------------------------------------


def test_is_suspicious_entry_flags_traversal_and_absolute():
    assert main.is_suspicious_entry("/etc/passwd") is True
    assert main.is_suspicious_entry("../escape.pdf") is True
    assert main.is_suspicious_entry("a/../b.pdf") is True
    # Backslash separators are normalized before the check.
    assert main.is_suspicious_entry("..\\windows\\evil.pdf") is True


def test_is_suspicious_entry_allows_normal_paths():
    assert main.is_suspicious_entry("filings/01_doc.pdf") is False
    assert main.is_suspicious_entry("doc.pdf") is False


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


def test_unique_slug_dedupes_with_fallback():
    used: set[str] = set()
    assert main.unique_slug("Hello World", "fb1", used) == "hello-world"
    # Second identical base collides -> fallback is appended.
    assert main.unique_slug("Hello World", "fb2", used) == "hello-world-fb2"
    assert used == {"hello-world", "hello-world-fb2"}


def test_unique_slug_uses_fallback_when_base_is_empty():
    used: set[str] = set()
    assert main.unique_slug("", "abc123", used) == "abc123"


# ---------------------------------------------------------------------------
# Heading shape
# ---------------------------------------------------------------------------


def test_normalize_heading_candidate_collapses_and_strips():
    assert main.normalize_heading_candidate("  FINAL   JUDGMENT  ") == "FINAL JUDGMENT"
    assert main.normalize_heading_candidate("·• ORDER |") == "ORDER"


def test_uppercase_letter_ratio():
    assert main.uppercase_letter_ratio("ABC") == 1.0
    assert main.uppercase_letter_ratio("aB") == 0.5
    assert main.uppercase_letter_ratio("123") == 0.0


def test_is_probable_heading_line_accepts_legal_titles():
    assert main.is_probable_heading_line("FINAL SUMMARY JUDGMENT") is True
    assert main.is_probable_heading_line("Motion to Compel Discovery") is True


def test_is_probable_heading_line_rejects_prose_and_fragments():
    assert main.is_probable_heading_line("This is body prose not a heading") is False
    # Starts lowercase.
    assert main.is_probable_heading_line("of counsel for plaintiff") is False
    # Ends on a dangling connective.
    assert main.is_probable_heading_line("MOTION FOR LEAVE TO") is False
    # Too short.
    assert main.is_probable_heading_line("OK") is False


# ---------------------------------------------------------------------------
# Legal keyword family (pattern order matters)
# ---------------------------------------------------------------------------


def test_legal_keyword_family_basic_mapping():
    assert main.legal_keyword_family("FINAL SUMMARY JUDGMENT") == "judgment"
    assert main.legal_keyword_family("CERTIFICATE OF SERVICE") == "certificate-of-service"
    assert main.legal_keyword_family("EXHIBIT A") == "exhibit"
    assert main.legal_keyword_family("just some words") is None


def test_legal_keyword_family_respects_pattern_priority():
    # MOTION is listed before ORDER, so a line containing both is a motion.
    assert main.legal_keyword_family("ORDER GRANTING MOTION") == "motion"
    # MOTION before JUDGMENT.
    assert main.legal_keyword_family("MOTION FOR SUMMARY JUDGMENT") == "motion"


# ---------------------------------------------------------------------------
# Heading boundary (strong vs weak)
# ---------------------------------------------------------------------------


def test_find_heading_boundary_strong_when_all_caps():
    result = main.find_heading_boundary("FINAL SUMMARY JUDGMENT\nbody text\n")
    assert result == ("FINAL SUMMARY JUDGMENT", True)


def test_find_heading_boundary_weak_when_title_case():
    result = main.find_heading_boundary("Motion to Compel Discovery\nbody text\n")
    assert result == ("Motion to Compel Discovery", False)


def test_find_heading_boundary_none_for_prose():
    assert main.find_heading_boundary("This is just body prose with no heading.") is None


# ---------------------------------------------------------------------------
# Title selection
# ---------------------------------------------------------------------------


def test_clean_title_prefers_legal_keyword_line():
    text = "GRAND CENTRAL PARK\nCause No. 25-09-14566\nFINAL SUMMARY JUDGMENT\nrest"
    assert main.clean_title(text, "fallback") == "FINAL SUMMARY JUDGMENT"


def test_clean_title_uses_first_substantial_line_without_keyword():
    text = "short\nThis is a long enough line\n"
    assert main.clean_title(text, "fallback") == "This is a long enough line"


def test_clean_title_falls_back_when_nothing_usable():
    assert main.clean_title("___\n··\n", "the-fallback") == "the-fallback"


# ---------------------------------------------------------------------------
# Curation overlay (whitelist enforcement)
# ---------------------------------------------------------------------------


def test_apply_metadata_overlay_only_allows_whitelisted_fields():
    base: dict = {}
    overlay = {
        "submissionType": "motion",
        "filingParty": "defendant",
        "sourcePageStart": 99,  # not whitelisted -> must be ignored
        "slug": "hacked",  # not whitelisted -> must be ignored
    }
    applied = main.apply_metadata_overlay(base, overlay, main.ALLOWED_CURATED_FIELDS)
    assert applied is True
    assert base == {"submissionType": "motion", "filingParty": "defendant"}


def test_apply_metadata_overlay_coerces_tags_to_str_list():
    base: dict = {}
    main.apply_metadata_overlay(base, {"tags": ["a", 1, True]}, main.ALLOWED_CURATED_FIELDS)
    assert base["tags"] == ["a", "1", "True"]


def test_apply_metadata_overlay_skips_non_list_tags():
    base: dict = {}
    applied = main.apply_metadata_overlay(base, {"tags": "nope"}, main.ALLOWED_CURATED_FIELDS)
    assert applied is False
    assert base == {}


def test_apply_metadata_overlay_returns_false_when_nothing_applies():
    base = {"existing": "kept"}
    applied = main.apply_metadata_overlay(base, {"unknown": "x"}, main.ALLOWED_CURATED_FIELDS)
    assert applied is False
    assert base == {"existing": "kept"}
