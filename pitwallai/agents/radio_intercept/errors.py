"""Decoder exception types."""


class DecodeValidationError(Exception):
    """Raised when decoder output fails Pydantic validation."""


class DecodeRuntimeError(Exception):
    """Raised when the decoder encounters a non-validation runtime failure."""
