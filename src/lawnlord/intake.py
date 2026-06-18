"""The intake-folder contract: where lawnlord reads inputs and writes output.

A consumer project (an "intake") has, by convention under its root:

    intake/   inputs — the source packet ZIP plus optional curated files
              (bundle-boundaries.json, corpus-curation.json)
    corpus/   generated output (regenerable)

An optional ``lawnlord.toml`` at the root overrides those locations, so a
project with an existing layout (e.g. src/filings + dist/corpus) can adopt
lawnlord without moving files:

    [lawnlord]
    intake = "src/filings"
    corpus = "dist/corpus"

This module is the single place that knows the layout; the rest of the
generator takes explicit paths/dicts and is layout-agnostic.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .console import console

CONFIG_FILENAME = "lawnlord.toml"
DEFAULT_INTAKE_DIRNAME = "intake"
DEFAULT_CORPUS_DIRNAME = "corpus"

# Curated-input filenames, resolved inside the intake dir.
MANUAL_BOUNDARIES_FILENAME = "bundle-boundaries.json"
GENERATED_BOUNDARIES_FILENAME = "bundle-boundaries.generated.json"
CURATION_FILENAME = "corpus-curation.json"


@dataclass(frozen=True)
class Intake:
    """Resolved input/output locations for one consumer project."""

    root: Path
    intake_dir: Path
    corpus_dir: Path

    @property
    def manual_boundaries_path(self) -> Path:
        return self.intake_dir / MANUAL_BOUNDARIES_FILENAME

    @property
    def curation_path(self) -> Path:
        return self.intake_dir / CURATION_FILENAME

    @property
    def generated_boundaries_path(self) -> Path:
        return self.intake_dir / GENERATED_BOUNDARIES_FILENAME


def load_intake(root: str | Path = ".") -> Intake:
    """Resolve the intake/corpus locations for a project root.

    Reads ``lawnlord.toml`` at the root when present (a parse error falls back
    to defaults rather than crashing); intake/corpus names may be relative to
    the root or absolute.
    """
    root = Path(root).resolve()
    intake_name = DEFAULT_INTAKE_DIRNAME
    corpus_name = DEFAULT_CORPUS_DIRNAME

    config_path = root / CONFIG_FILENAME
    if config_path.exists():
        try:
            cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
            section = cfg.get("lawnlord", {})
        except (OSError, tomllib.TOMLDecodeError) as exc:
            console.print(f"[red]Could not parse {config_path}: {exc} — using defaults.[/]")
            section = {}
        intake_name = section.get("intake", intake_name)
        corpus_name = section.get("corpus", corpus_name)

    return Intake(
        root=root,
        intake_dir=(root / intake_name).resolve(),
        corpus_dir=(root / corpus_name).resolve(),
    )


def resolve_packet(intake: Intake, explicit: str | Path | None = None) -> Path:
    """Find the source packet ZIP: an explicit path if given, otherwise the
    single ``*.zip`` in the intake dir. Errors (SystemExit) if none or more
    than one is found and no explicit path was given."""
    if explicit:
        packet = Path(explicit).resolve()
        if not packet.exists():
            raise FileNotFoundError(packet)
        return packet

    zips = sorted(intake.intake_dir.glob("*.zip"))
    if not zips:
        console.print(
            f"[red]No packet ZIP found in {intake.intake_dir}.[/]"
            " Drop the source packet there, or pass one explicitly."
        )
        raise SystemExit(1)
    if len(zips) > 1:
        console.print(
            f"[red]Multiple ZIPs in {intake.intake_dir}; pass one explicitly:[/]"
        )
        for z in zips:
            console.print(f"  - {z.name}")
        raise SystemExit(1)
    return zips[0].resolve()


_CONFIG_TEMPLATE = """\
# lawnlord configuration. Paths are relative to this file's directory
# (or absolute). Delete a key to use its default.
[lawnlord]
# Where the intake lives. Two supported layouts:
#   local  -> "intake"                  (provider folders under ./intake/)
#   repo   -> "../gcp-hoa-case/intake"  (case data in a separate repo)
# The LAWNLORD_INTAKE env var overrides this for provider commands
# (compare/index/pack/assemble/bundle/combine), which also accept a bare
# provider name (e.g. `lawnlord compare combo`) resolved under this root.
intake = "intake"   # inputs: the source packet ZIP + optional curated files
corpus = "corpus"   # generated output (regenerable)
"""

_INTAKE_README = """\
# Intake

Drop the source packet here, then build the corpus:

- **`<packet>.zip`** — the downloaded court-record packet (one ZIP of PDFs).
  Exactly one `*.zip` is expected; pass `--packet` to disambiguate more.
- **`bundle-boundaries.json`** *(optional)* — curated manual section
  boundaries (detection Tier 1; always wins). Generate a draft with
  `lawnlord emit-boundaries`, review it, then save it here under this name.
- **`corpus-curation.json`** *(optional)* — curated metadata overlay
  (only whitelisted fields; never overrides generated provenance).

Then run `lawnlord build` from the project root. Output lands in the configured
corpus directory (regenerable — safe to delete and rebuild).
"""


def scaffold(root: str | Path = ".", force: bool = False) -> list[Path]:
    """Scaffold an intake folder under ``root``: create the intake/ dir, a
    starter ``lawnlord.toml``, and an intake README explaining what to drop
    where. Existing files are left alone unless ``force``. Returns the paths
    created or overwritten."""
    root = Path(root).resolve()
    touched: list[Path] = []

    intake_dir = root / DEFAULT_INTAKE_DIRNAME
    if not intake_dir.exists():
        intake_dir.mkdir(parents=True)
        touched.append(intake_dir)

    config_path = root / CONFIG_FILENAME
    if force or not config_path.exists():
        config_path.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
        touched.append(config_path)

    readme_path = intake_dir / "README.md"
    if force or not readme_path.exists():
        readme_path.write_text(_INTAKE_README, encoding="utf-8")
        touched.append(readme_path)

    return touched
