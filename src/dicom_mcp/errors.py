"""Custom exceptions for DICOM MCP."""

from __future__ import annotations

from typing import Any, Dict, Optional


class DicomError(Exception):
    """Base class for DICOM MCP errors."""

    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "type": self.__class__.__name__,
            "message": str(self),
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class DicomAssociationError(DicomError):
    """Raised when a DICOM association cannot be established."""


class DicomOperationError(DicomError):
    """Raised when a DICOM operation fails."""


class DicomConfigurationError(DicomError):
    """Raised when configuration is invalid or missing."""


class StorageSecurityError(DicomError):
    """Raised when storage path validation fails."""
