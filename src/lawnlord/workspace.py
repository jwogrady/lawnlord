"""The case workspace: resolve a ``Case`` from a provider intake folder and
expose the input paths plus the output subtree, with no ``REPO_ROOT`` coupling.

``Case.from_intake("…/intake/ody")`` reads the provider export (via the
:mod:`lawnlord.providers` adapter) into a typed model and pins where generated
artifacts go under a separate output root (the ``case_dir``, default: cwd). The
case *identity* — and the case slug — derives from ``caseNumber`` in the intake
metadata, never from the provider folder name (``ody``).

This module computes paths only; it creates nothing (scaffolding the output
tree and opening the DuckDB index are separate steps).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .providers import (
    CaseIdentity,
    CaseModel,
    DocumentRef,
    Event,
    Party,
    parse_provider,
)
from .providers import case_slug as _case_slug

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
    """A resolved case: its provider intake folder, the parsed model, and the
    output root where lawnlord writes generated artifacts."""

    intake_dir: Path
    provider: str
    case_dir: Path
    model: CaseModel

    @classmethod
    def from_intake(
        cls, intake_dir: str | Path, case_dir: str | Path | None = None
    ) -> Case:
        """Resolve a case from a provider intake folder.

        ``intake_dir`` is the provider export (its name selects the adapter);
        ``case_dir`` is the output root for generated artifacts (default: cwd).
        """
        intake_dir = Path(intake_dir).resolve()
        if not intake_dir.is_dir():
            raise FileNotFoundError(f"intake folder not found: {intake_dir}")
        if not (intake_dir / "filings").is_dir():
            raise FileNotFoundError(
                f"{intake_dir} is not a provider intake folder — it has no filings/ directory "
                "of PDFs. compare/index/pack/assemble/bundle expect a provider export (case JSON "
                "+ a filings/ directory), e.g. intake/combo or intake/ody. A packet ZIP (e.g. "
                "CA763CC5.zip) or a re:SearchTX download (zip + meta.json) is not yet a provider "
                "folder — its PDFs must be extracted into filings/ first."
            )
        provider = intake_dir.name
        model = parse_provider(provider, intake_dir)
        case_dir = Path(case_dir).resolve() if case_dir else Path.cwd()
        return cls(
            intake_dir=intake_dir,
            provider=provider,
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

    # --- intake (input) paths ----------------------------------------------

    @property
    def case_summary_path(self) -> Path:
        return self.intake_dir / "case-summary.json"

    @property
    def case_history_path(self) -> Path:
        return self.intake_dir / "case-history.json"

    @property
    def register_of_actions_path(self) -> Path:
        return self.intake_dir / "register-of-actions.json"

    @property
    def filings_json_path(self) -> Path:
        return self.intake_dir / "filings.json"

    @property
    def filings_dir(self) -> Path:
        return self.intake_dir / "filings"

    # --- output paths (under case_dir; not created here) -------------------

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
