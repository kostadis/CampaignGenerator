"""Library passage search: whole-section search over converted DMsGuild books.

No LLM calls. All mempalace access goes through ``pipelines/rlm/mempalace_client``.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Shared by every ``library`` subcommand (contracts/cli.md)."""

    OK = 0
    FAILED = 1
    USAGE = 2
    NOT_CONFIGURED = 3
    NOT_BUILT = 4
    EMBEDDER_MISMATCH = 5
    REFUSED = 6


class LibraryError(RuntimeError):
    """Base: every refusal carries the exit code the CLI maps it to."""

    exit_code = ExitCode.FAILED
    code = "failed"


class SourceUnavailable(LibraryError):
    exit_code = ExitCode.FAILED
    code = "source_unavailable"


class NotConfigured(LibraryError):
    exit_code = ExitCode.NOT_CONFIGURED
    code = "not_configured"


class NotBuilt(LibraryError):
    exit_code = ExitCode.NOT_BUILT
    code = "not_built"


class EmbedderMismatch(LibraryError):
    exit_code = ExitCode.EMBEDDER_MISMATCH
    code = "embedder_mismatch"


class PalaceRefused(LibraryError):
    exit_code = ExitCode.REFUSED
    code = "refused"
