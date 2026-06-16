"""Test bootstrap.

The package lives under src/ (src/lawnlord/), so tests import it as
``import lawnlord`` (aliased to ``main`` in the test modules). pytest is
configured with ``pythonpath = ["src"]`` in pyproject.toml; this conftest adds
the same entry as a belt-and-braces fallback so the suite runs even when the
package is not installed and pytest is invoked from an unexpected cwd.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
