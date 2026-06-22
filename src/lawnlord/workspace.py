"""The case workspace: a resolved ``Case`` — its intake (the zip's extracted
contents), the parsed model, and the output root where lawnlord writes the
DuckDB index.

The model is read from the deterministic intake zip (schema.json + data.json +
files/). The reader that turns the zip into a :class:`~lawnlord.models.CaseModel`
lands on the next branch; this module computes paths and exposes the model, and
creates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import (
    FILES_DIRNAME,
    CaseIdentity,
    CaseModel,
    DocumentRef,
    Event,
    Party,
    case_slug as _case_slug,
)

# The generated output subtree under a case_dir (created by the scaffold step).
OUTPUT_SUBDIRS = (
    "intake",
    "artifacts",
    "knowledgebase",
    "extracted",
    "analysis",
    "outputs",
    "manifests",
)


@dataclass(frozen=True)
class Case:
    """A resolved case: its intake folder (the zip's extracted contents), the
    parsed model, and the output root where lawnlord writes the index."""

    intake_dir: Path
    provider: str
    case_dir: Path
    model: CaseModel

    @classmethod
    def from_intake(
        cls, intake_dir: str | Path, case_dir: str | Path | None = None
    ) -> Case:
        """Resolve a case from an extracted intake zip.

        ``intake_dir`` holds the zip's contents (``data.json`` + ``schema.json``
        + ``files/``); ``case_dir`` is the output root for the DuckDB index
        (default: cwd). The model is read and validated by
        :func:`lawnlord.reader.load_case_model`.
        """
        from .reader import load_case_model

        intake_dir = Path(intake_dir).resolve()
        if not intake_dir.is_dir():
            raise FileNotFoundError(f"intake folder not found: {intake_dir}")
        if not (intake_dir / "data.json").is_file():
            raise FileNotFoundError(
                f"{intake_dir} is not an extracted intake zip — it has no data.json. "
                "Run `lawnlord import <zip>`, or point at the zip's extracted contents "
                "(data.json + schema.json + files/)."
            )
        model = load_case_model(intake_dir)
        case_dir = Path(case_dir).resolve() if case_dir else Path.cwd()
        return cls(
            intake_dir=intake_dir,
            provider=model.provider,
            case_dir=case_dir,
            model=model,
        )

    # --- model passthroughs -------------------------------------------------

    @property
    def identity(self) -> CaseIdentity:
        return self.model.identity

    @property
    def parties(self) -> tuple[Party, ...]:
        return self.model.parties

    @property
    def events(self) -> tuple[Event, ...]:
        return self.model.events

    @property
    def documents(self) -> tuple[DocumentRef, ...]:
        return self.model.documents

    @property
    def case_number(self) -> str:
        return self.model.identity.case_number

    @property
    def case_slug(self) -> str:
        return _case_slug(self.case_number)

    # --- paths --------------------------------------------------------------

    @property
    def files_dir(self) -> Path:
        """The filed PDFs, under ``files/`` in the zip standard."""
        return self.intake_dir / FILES_DIRNAME

    @property
    def corpus_dir(self) -> Path:
        return self.case_dir / "extracted" / "corpus"

    @property
    def duckdb_path(self) -> Path:
        return self.case_dir / "lawnlord.duckdb"

    @property
    def case_json_path(self) -> Path:
        return self.case_dir / "manifests" / "case.json"

    def output_dirs(self) -> tuple[Path, ...]:
        """The output subtree paths under ``case_dir`` (for the scaffold step)."""
        return tuple(self.case_dir / name for name in OUTPUT_SUBDIRS)
