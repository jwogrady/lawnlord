"""Per-run file logging for the transcription pipeline.

Additive to the user-facing Rich console (``console.py``), which stays the sole
human-readable sink. This module gives the pipeline a plain ``logging.Logger``
("lawnlord") backed by a per-run log file under ``case_dir/logs/`` so that the
per-page failures the transcribe/escalate passes otherwise swallow leave a
durable, machine-greppable record (page id, model, exception, traceback).

The file name carries a timestamp run id so consecutive runs never overwrite
each other. The level is configurable without code edits via the
``LAWNLORD_LOG_LEVEL`` env var (or the caller passing ``level``); it defaults to
INFO — useful without being noisy, and does not touch console verbosity.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

# The pipeline logger. Modules log via ``logging.getLogger("lawnlord")`` (or a
# child, e.g. ``"lawnlord.transcribe"``) so all records flow through the one
# FileHandler this helper installs.
LOGGER_NAME = "lawnlord"

# Env var that overrides the default level without a code change.
LEVEL_ENV_VAR = "LAWNLORD_LOG_LEVEL"
DEFAULT_LEVEL = logging.INFO


def _resolve_level(level: int | str | None) -> int:
    """The effective log level: an explicit ``level`` arg wins, else the
    ``LAWNLORD_LOG_LEVEL`` env var (name or number), else INFO. An unrecognized
    value falls back to INFO rather than raising — logging is best-effort."""
    candidate = level if level is not None else os.environ.get(LEVEL_ENV_VAR)
    if candidate is None:
        return DEFAULT_LEVEL
    if isinstance(candidate, int):
        return candidate
    name = str(candidate).strip().upper()
    if name.isdigit():
        return int(name)
    resolved = logging.getLevelName(name)
    return resolved if isinstance(resolved, int) else DEFAULT_LEVEL


def setup_run_logging(
    case_dir: str | Path,
    *,
    run_id: str | None = None,
    level: int | str | None = None,
) -> Path:
    """Configure the ``lawnlord`` logger with a per-run FileHandler and return
    the log file path.

    The file lands under ``case_dir/logs/`` (created if absent), alongside the
    other output subtrees, named ``transcribe-<run_id>.log`` where ``run_id``
    defaults to a UTC timestamp so consecutive runs do not overwrite each other.
    Idempotent per run: re-installs cleanly (clears prior handlers) so a second
    call in the same process does not double-log. Never raises — a failure to
    open the file degrades to no file handler rather than aborting the run.
    """
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_resolve_level(level))
    # Records stay in our file handler; don't also bubble to the root logger
    # (which would print to stderr and pollute the user-facing console).
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logs_dir = Path(case_dir) / "logs"
    log_path = logs_dir / f"transcribe-{run_id}.log"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        # Best-effort: if the log file can't be opened, the run proceeds without
        # a file sink rather than failing on a logging concern.
        return log_path
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return log_path


def get_logger() -> logging.Logger:
    """The pipeline logger. Safe to call before :func:`setup_run_logging`; it
    just has no file handler yet (records go nowhere, harmlessly)."""
    return logging.getLogger(LOGGER_NAME)
