"""Shared refusal type and exit codes for the delta family (contracts/cli.md)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_REFUSAL = 1
EXIT_USAGE = 2  # usage error or empty selection
EXIT_STALE = 3  # stale input or conflict
EXIT_PARTIAL = 4
EXIT_RECOVERY = 5  # recovery required


class DeltaRefusal(Exception):
    """A deliberate refusal carrying the process exit code the CLI must use."""

    def __init__(self, message: str, exit_code: int = EXIT_REFUSAL) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
