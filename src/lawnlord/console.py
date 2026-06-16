"""Shared Rich console singleton.

Every module that prints human-facing output (warnings, progress, summary
tables) imports this one Console so output goes through a single sink.
"""

from rich.console import Console

console = Console()
