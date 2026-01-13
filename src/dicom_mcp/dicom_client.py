"""
DICOM Client.

This module provides a clean interface to pynetdicom functionality,
abstracting the details of DICOM networking.
"""

from .dicom_client_base import DicomClientBase
from .dicom_client_downloads import DicomClientDownloadMixin
from .dicom_client_moves import DicomClientMoveMixin
from .dicom_client_pdf import DicomClientPdfMixin
from .dicom_client_queries import DicomClientQueryMixin


class DicomClient(
    DicomClientBase,
    DicomClientQueryMixin,
    DicomClientMoveMixin,
    DicomClientDownloadMixin,
    DicomClientPdfMixin,
):
    """DICOM networking client that handles communication with DICOM nodes."""

