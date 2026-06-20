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
        """Resolve a case from the intake zip's extracted contents.

        The zip → CaseModel reader lands on the next refactor branch; until then
        this raises so no stale provider-parsing path is silently used.
        """
        raise NotImplementedError(
            "The intake-zip reader (data.json -> CaseModel) lands on the next "
            "branch. The old ody/txe/combo provider adapters were removed in "
            "favor of the deterministic zip standard."
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
