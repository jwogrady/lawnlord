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
# Case slug
# ---------------------------------------------------------------------------


def test_case_slug_preserves_case_number():
    assert main.case_slug("25-09-14566") == "25-09-14566"
    assert main.case_slug("") == "case"
