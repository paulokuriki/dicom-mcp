"""
Core tool registrations for node management and manifest helpers.
"""

import logging
from typing import Any, Dict, List

from mcp.server.fastmcp import Context, FastMCP

from .attributes import ATTRIBUTE_PRESETS
from .config import DicomConfiguration
from .errors import DicomConfigurationError
from .manifest import build_manifest
from .server_tools_common import ToolDependencies

logger = logging.getLogger("dicom_mcp")


def register_core_tools(mcp: FastMCP, deps: ToolDependencies, server_name: str) -> None:
    """Register core MCP tools."""

    @mcp.tool()
    def list_dicom_nodes(ctx: Context = None) -> Dict[str, Any]:
        """List all configured DICOM nodes and their connection information.

        This tool returns information about all configured DICOM nodes in the system
        and shows which node is currently selected for operations. It also provides
        registry metadata used by downstream node resolvers.

        Returns:
            Dictionary containing:
            - current_node: The currently selected DICOM node name
            - current_calling_aet: The currently selected calling AE name or AE title
            - current_calling_ae_title: The resolved calling AE title in use
            - nodes: List of node registry entries with canonical name, AE title,
              and optional aliases/description
            - nodes_legacy: Backward-compatible list of {name: description}
            - calling_aets: List of configured calling AE entries (if any)

        Example:
            {
                "current_node": "pacs1",
                "current_calling_aet": "default",
                "current_calling_ae_title": "MCPSCU",
                "nodes": [
                    {
                        "name": "pacs1",
                        "ae_title": "PACS1",
                        "aliases": ["main", "primary"],
                        "description": "Primary PACS",
                    },
                    {
                        "name": "orthanc",
                        "ae_title": "ORTHANC",
                    },
                ],
                "nodes_legacy": [
                    {"pacs1": "Primary PACS"},
                    {"orthanc": ""},
                ],
                "calling_aets": [
                    {
                        "name": "default",
                        "ae_title": "MCPSCU",
                        "description": "Default calling AE",
                    }
                ],
            }
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config

        current_node = config.current_node
        nodes = []
        nodes_legacy = []
        for node_name, node in config.nodes.items():
            node_entry = {
                "name": node_name,
                "ae_title": node.ae_title,
            }
            if node.description:
                node_entry["description"] = node.description
            if node.aliases:
                node_entry["aliases"] = list(node.aliases)
            nodes.append(node_entry)
            nodes_legacy.append({node_name: node.description})

        calling_aets = []
        for aet_name, calling_aet in config.calling_aets.items():
            aet_entry = {
                "name": aet_name,
                "ae_title": calling_aet.ae_title,
            }
            if calling_aet.description:
                aet_entry["description"] = calling_aet.description
            if calling_aet.aliases:
                aet_entry["aliases"] = list(calling_aet.aliases)
            calling_aets.append(aet_entry)

        return {
            "current_node": current_node,
            "current_calling_aet": config.calling_aet,
            "current_calling_ae_title": config.calling_aet_title,
            "nodes": nodes,
            "nodes_legacy": nodes_legacy,
            "calling_aets": calling_aets,
        }

    @mcp.tool()
    def get_manifest(ctx: Context = None) -> Dict[str, Any]:
        """Return the MCP manifest for schema/version contract validation."""
        return build_manifest(server_name=server_name)

    @mcp.tool()
    def switch_dicom_node(node_name: str, ctx: Context = None) -> Dict[str, Any]:
        """Switch the active DICOM node connection to a different configured node.

        This tool changes which DICOM node (PACS, workstation, etc.) subsequent operations
        will connect to. The node must be defined in the configuration file.

        Args:
            node_name: The name of the node to switch to, must match a name in the configuration

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the switch was successful
            - message: Description of the operation result or error

        Example:
            {
                "success": true,
                "message": "Switched to DICOM node: orthanc"
            }

        Notes:
            Returns success False if the node name is not found.
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config: DicomConfiguration = dicom_ctx.config

        logger.info(
            deps.format_log_event(
                "switch_dicom_node",
                config,
                target_node=node_name,
            )
        )

        # Normalize node name for case-insensitive lookup
        node_key = node_name.lower()

        # Check if node exists
        if node_key not in config.nodes:
            return deps.tool_error_response(
                "switch_dicom_node",
                config,
                DicomConfigurationError(f"Node '{node_name}' not found in configuration"),
            )

        # Update configuration
        config.current_node = node_key

        return {
            "success": True,
            "message": f"Switched to DICOM node: {node_name}",
        }

    @mcp.tool()
    def switch_calling_aet(aet_name: str, ctx: Context = None) -> Dict[str, Any]:
        """Switch the active calling AE title used for new associations.

        This tool updates the local calling AE title used when establishing
        associations with the current DICOM node. The requested AE title must
        be defined in the configuration under calling_aets.

        Args:
            aet_name: The name, alias, or AE title of the calling AET to use

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the switch was successful
            - message: Description of the operation result or error

        Raises:
            ValueError: If no calling AETs are configured or the name is unknown
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config: DicomConfiguration = dicom_ctx.config

        logger.info(
            deps.format_log_event(
                "switch_calling_aet",
                config,
                target_calling_aet=aet_name,
            )
        )

        try:
            resolved_name, calling_aet = config.resolve_calling_aet(aet_name)
            config.calling_aet = resolved_name
        except Exception as exc:
            return deps.tool_error_response(
                "switch_calling_aet",
                config,
                DicomConfigurationError(str(exc)),
            )

        return {
            "success": True,
            "message": (
                f"Switched calling AE title to: {calling_aet.ae_title} ({resolved_name})"
            ),
        }

    @mcp.tool()
    def verify_connection(ctx: Context = None) -> Dict[str, Any]:
        """Verify connectivity to the current DICOM node using C-ECHO.

        This tool performs a DICOM C-ECHO operation (similar to a network ping) to check
        if the currently selected DICOM node is reachable and responds correctly. This is
        useful to troubleshoot connection issues before attempting other operations.

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the connection succeeded
            - message: Description of the connection status
            - details: Connection details (node, host, port, AE titles)

        Example:
            {
                "success": true,
                "message": "Connection successful to 192.168.1.100:104 (Called AE: ORTHANC, Calling AE: CLIENT)",
                "details": {
                    "node_name": "orthanc",
                    "host": "192.168.1.100",
                    "port": 104,
                    "called_ae_title": "ORTHANC",
                    "calling_ae_title": "CLIENT"
                }
            }
        """
        dicom_ctx = ctx.request_context.lifespan_context
        config = dicom_ctx.config
        client = deps.create_client(config)

        success, message = client.verify_connection()
        return {
            "success": success,
            "message": message,
            "details": {
                "node_name": config.current_node,
                "host": client.host,
                "port": client.port,
                "called_ae_title": client.called_aet,
                "calling_ae_title": client.calling_aet,
            },
        }

    @mcp.tool()
    def get_attribute_presets() -> Dict[str, Dict[str, List[str]]]:
        """Get all available attribute presets for DICOM queries.

        This tool returns the defined attribute presets that can be used with the
        query_* functions. It shows which DICOM attributes are included in each
        preset (minimal, standard, extended) for each query level.

        Returns:
            Dictionary organized by query level (patient, study, series, instance),
            with each level containing the attribute presets and their associated
            DICOM attributes.

        Example:
            {
                "patient": {
                    "minimal": ["PatientID", "PatientName"],
                    "standard": ["PatientID", "PatientName", "PatientBirthDate", "PatientSex"],
                    "extended": ["PatientID", "PatientName", "PatientBirthDate", "PatientSex", ...]
                },
                "study": {
                    "minimal": ["StudyInstanceUID", "StudyDate"],
                    "standard": ["StudyInstanceUID", "StudyDate", "StudyDescription", ...],
                    "extended": ["StudyInstanceUID", "StudyDate", "StudyDescription", ...]
                },
                ...
            }
        """
        return ATTRIBUTE_PRESETS
