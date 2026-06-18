"""Custom exceptions for PatchDB."""

from __future__ import annotations


class PatchDBError(RuntimeError):
    """Base exception class for all PatchDB errors."""
    pass


class InvalidJSONError(PatchDBError):
    """Raised when the AI response is not valid JSON."""
    pass


class ModelSaidNo(PatchDBError):
    """Raised when the AI model returns an explicit error or invalid structure."""
    pass
