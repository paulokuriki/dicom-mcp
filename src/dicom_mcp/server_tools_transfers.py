"""
Transfer tool registrations (downloads, moves, PDF extraction).
"""

import os
import time
from typing import Any, Dict, List

from mcp.server.fastmcp import Context, FastMCP

from .dicom_client import DicomClient
from .errors import DicomConfigurationError, DicomOperationError
from .server_tools_common import ToolDependencies


def register_transfer_tools(mcp: FastMCP, deps: ToolDependencies) -> None:
    """Register transfer-related MCP tools."""

    @mcp.tool()
    def extract_pdf_text_from_dicom(
        study_instance_uid: str,
        series_instance_uid: str,
        sop_instance_uid: str,
        keep_files: bool = False,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Retrieve a DICOM instance with encapsulated PDF and extract its text content.

        This tool retrieves a DICOM instance containing an encapsulated PDF document,
        extracts the PDF, and converts it to text. This is particularly useful for
        medical reports stored as PDFs within DICOM format (e.g., radiology reports,
        clinical documents).

        Args:
            study_instance_uid: The unique identifier for the study (required)
            series_instance_uid: The unique identifier for the series within the study (required)
            sop_instance_uid: The unique identifier for the specific DICOM instance (required)
            keep_files: Keep retrieved files in the downloads directory (default False)

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the operation was successful
            - message: Description of the operation result or error
            - text_content: The extracted text from the PDF (if successful)
            - file_path: Path to the DICOM file when kept (if keep_files is True)
            - pdf_metadata: PDF metadata including page count, size, and text extraction status

        Example:
            {
                "success": true,
                "message": "Successfully extracted text from PDF in DICOM",
                "text_content": "Patient report contents...",
                "file_path": "./downloads/reports/1.2.3.4.5.6.7.8_1700000000000/1.2.3.4.5.6.7.8.dcm",
                "pdf_metadata": {
                    "page_count": 2,
                    "pdf_size_bytes": 15432,
                    "text_empty": false,
                    "text_length": 1200
                }
            }
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config
        client = deps.create_client(config)
        output_dir = None
        if keep_files:
            download_root = deps.download_root(config)
            safe_uid = DicomClient._sanitize_filename(sop_instance_uid)
            output_dir = os.path.join(download_root, "reports", f"{safe_uid}_{int(time.time() * 1000)}")

        try:
            return client.extract_pdf_text_from_dicom(
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
                sop_instance_uid=sop_instance_uid,
                keep_files=keep_files,
                output_dir=output_dir,
                file_permissions=config.storage.file_permissions,
                dir_permissions=config.storage.dir_permissions,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "extract_pdf_text_from_dicom",
                config,
                DicomOperationError(str(exc)),
                base_payload={
                    "text_content": "",
                    "file_path": "",
                    "pdf_metadata": {
                        "page_count": 0,
                        "pdf_size_bytes": 0,
                        "text_empty": True,
                        "text_length": 0,
                    },
                },
            )

    @mcp.tool()
    def download_studies(
        study_instance_uids: List[str],
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Download one or more studies to a local download directory."""
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config
        download_root = deps.download_root(config)
        client = deps.create_client(config)
        try:
            return client.download_studies(
                study_instance_uids,
                download_root,
                file_permissions=config.storage.file_permissions,
                dir_permissions=config.storage.dir_permissions,
                source_node=config.current_node,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "download_studies",
                config,
                DicomOperationError(str(exc)),
                base_payload={
                    "items": [],
                    "files_downloaded": 0,
                },
            )

    @mcp.tool()
    def download_series(
        study_instance_uid: str,
        series_instance_uids: List[str],
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Download specific series for a study to the local download directory."""
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config
        download_root = deps.download_root(config)
        client = deps.create_client(config)
        try:
            return client.download_series(
                study_instance_uid,
                series_instance_uids,
                download_root,
                file_permissions=config.storage.file_permissions,
                dir_permissions=config.storage.dir_permissions,
                source_node=config.current_node,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "download_series",
                config,
                DicomOperationError(str(exc)),
                base_payload={
                    "items": [],
                    "files_downloaded": 0,
                },
            )

    @mcp.tool()
    def download_instances(
        study_instance_uid: str,
        series_instance_uid: str,
        sop_instance_uids: List[str] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Download instances for a given series (optionally filtering by SOP Instance UID)."""
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config
        download_root = deps.download_root(config)
        client = deps.create_client(config)
        try:
            return client.download_instances(
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
                download_root=download_root,
                sop_instance_uids=sop_instance_uids,
                file_permissions=config.storage.file_permissions,
                dir_permissions=config.storage.dir_permissions,
                source_node=config.current_node,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "download_instances",
                config,
                DicomOperationError(str(exc)),
                base_payload={
                    "items": [],
                    "files_downloaded": 0,
                },
            )

    @mcp.tool()
    def move_series(
        destination_node: str,
        series_instance_uid: str,
        study_instance_uid: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Move a DICOM series to another DICOM node.

        This tool transfers a specific series from the current DICOM server to a
        destination DICOM node. It requires a specific SeriesInstanceUID obtained
        from a prior query_series() call.

        NOTE: This tool does NOT accept search filters (modality, description, etc.).
        To move series matching criteria, first use query_series() to find matching UIDs,
        then call move_series() for each result.

        Args:
            destination_node: Name of the destination node as defined in the configuration
                (case-insensitive, e.g., "radiant" or "RADIANT")
            series_instance_uid: The unique identifier for the series to be moved
                (required, obtained from query_series results)
            study_instance_uid: Optional study identifier for stricter PACS requirements

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the operation was successful
            - message: Description of the operation result or error
            - completed: Number of successfully transferred instances
            - failed: Number of failed transfers
            - warning: Number of transfers with warnings

        Example:
            {
                "success": true,
                "message": "C-MOVE operation completed successfully",
                "completed": 120,
                "failed": 0,
                "warning": 0
            }
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config

        # Validate series_instance_uid is provided
        if not series_instance_uid or not series_instance_uid.strip():
            return deps.tool_error_response(
                "move_series",
                config,
                DicomOperationError(
                    "series_instance_uid is required. This tool moves a single series by UID. "
                    "To move series matching search criteria, first call query_series() "
                    "with your filters, then call move_series() for each result's SeriesInstanceUID."
                ),
            )

        client = deps.create_client(config)

        # Normalize node name for case-insensitive lookup
        node_key = destination_node.lower()

        # Check if destination node exists
        if node_key not in config.nodes:
            return deps.tool_error_response(
                "move_series",
                config,
                DicomConfigurationError(
                    f"Destination node '{destination_node}' not found in configuration"
                ),
            )

        # Get the destination AE title
        destination_ae = config.nodes[node_key].ae_title

        # Execute the move operation
        try:
            result = client.move_series(
                destination_ae=destination_ae,
                series_instance_uid=series_instance_uid,
                study_instance_uid=study_instance_uid or None,
            )
            return result
        except Exception as exc:
            return deps.tool_error_response(
                "move_series",
                config,
                DicomOperationError(str(exc)),
                base_payload={
                    "completed": 0,
                    "failed": 0,
                    "warning": 0,
                },
            )

    @mcp.tool()
    def move_study(
        destination_node: str,
        study_instance_uid: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Move a DICOM study to another DICOM node.

        This tool transfers an entire study from the current DICOM server to a
        destination DICOM node. It requires a specific StudyInstanceUID obtained
        from a prior query_studies() call.

        NOTE: This tool does NOT accept search filters (modality, date range, description).
        To move studies matching criteria, first use query_studies() to find matching UIDs,
        then call move_study() for each result.

        Args:
            destination_node: Name of the destination node as defined in the configuration
                (case-insensitive, e.g., "radiant" or "RADIANT")
            study_instance_uid: The unique identifier for the study to be moved
                (required, obtained from query_studies results)

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the operation was successful
            - message: Description of the operation result or error
            - completed: Number of successfully transferred instances
            - failed: Number of failed transfers
            - warning: Number of transfers with warnings

        Example:
            {
                "success": true,
                "message": "C-MOVE operation completed successfully",
                "completed": 256,
                "failed": 0,
                "warning": 0
            }
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config

        # Validate study_instance_uid is provided
        if not study_instance_uid or not study_instance_uid.strip():
            return deps.tool_error_response(
                "move_study",
                config,
                DicomOperationError(
                    "study_instance_uid is required. This tool moves a single study by UID. "
                    "To move studies matching search criteria, first call query_studies() "
                    "with your filters, then call move_study() for each result's StudyInstanceUID."
                ),
            )

        client = deps.create_client(config)

        # Normalize node name for case-insensitive lookup
        node_key = destination_node.lower()

        # Check if destination node exists
        if node_key not in config.nodes:
            return deps.tool_error_response(
                "move_study",
                config,
                DicomConfigurationError(
                    f"Destination node '{destination_node}' not found in configuration"
                ),
            )

        # Get the destination AE title
        destination_ae = config.nodes[node_key].ae_title

        # Execute the move operation
        try:
            result = client.move_study(
                destination_ae=destination_ae,
                study_instance_uid=study_instance_uid,
            )
            return result
        except Exception as exc:
            return deps.tool_error_response(
                "move_study",
                config,
                DicomOperationError(str(exc)),
                base_payload={
                    "completed": 0,
                    "failed": 0,
                    "warning": 0,
                },
            )
