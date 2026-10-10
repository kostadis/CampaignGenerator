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


class PromotionMigrationRequired(PromotionError):
    def __init__(self, message: str = "managed grounding bundle migration is required") -> None:
        super().__init__(message, code="PROMOTION_MIGRATION_REQUIRED")


class PromotionRecoveryRequired(PromotionError):
    def __init__(self, message: str = "grounding activation requires explicit recovery") -> None:
        super().__init__(message, code="PROMOTION_RECOVERY_REQUIRED")
