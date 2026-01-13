"""
Shared tool registration helpers.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict

from .config import DicomConfiguration
from .dicom_client import DicomClient


@dataclass(frozen=True)
class ToolDependencies:
    """Dependencies shared across tool modules."""

    create_client: Callable[[DicomConfiguration], DicomClient]
    download_root: Callable[[DicomConfiguration], str]
    format_log_event: Callable[..., str]
    tool_error_response: Callable[
        [str, DicomConfiguration | None, Exception, Dict[str, Any] | None],
        Dict[str, Any],
    ]
