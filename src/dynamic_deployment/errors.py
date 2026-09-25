"""Operator-facing errors without secret content."""

class ValidationError(ValueError):
    """Configuration or preflight input is invalid."""


class OperationError(RuntimeError):
    """An operation failed or returned an unknown result."""
