"""Stable refusal errors for managed grounding promotion."""

from __future__ import annotations


class PromotionError(ValueError):
    """A deliberate refusal with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "PROMOTION_INVALID") -> None:
        super().__init__(message)
        self.code = code


class PromotionPathError(PromotionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="PROMOTION_PATH_CONFLICT")


class PromotionStaleError(PromotionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="PROMOTION_STALE_PREVIEW")


MIGRATION_COMMAND = "migrate_grounding_bundle --campaign-dir {campaign} --dry-run --json"


def migration_command(campaign_dir: object | None = None) -> str:
    """The exact out-of-band command that inspects a campaign's migration (XIII)."""
    return MIGRATION_COMMAND.format(campaign=campaign_dir if campaign_dir is not None else "<campaign>")


class PromotionMigrationRequired(PromotionError):
    """Refusal naming the migration command, filled with the campaign when known."""

    def __init__(self, message: str | None = None, *, campaign_dir: object | None = None) -> None:
        self.campaign_dir = campaign_dir
        command = migration_command(campaign_dir)
        if message is None:
            message = f"managed grounding bundle migration is required; run `{command}`"
        elif "migrate_grounding_bundle" not in message:
            message = f"{message}; run `{command}`"
        super().__init__(message, code="PROMOTION_MIGRATION_REQUIRED")


def recover_command(operation_id: str) -> str:
    """The exact command that resolves one promotion operation."""
    return f"summary_native promotion recover --operation {operation_id}"


class PromotionRecoveryRequired(PromotionError):
    def __init__(
        self, message: str = "grounding activation requires explicit recovery", *,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(message, code="PROMOTION_RECOVERY_REQUIRED")
        self.operation_id = operation_id
