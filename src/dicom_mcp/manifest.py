"""Manifest schema/version contract for the DICOM MCP server."""

from __future__ import annotations

from importlib import metadata
from importlib.metadata import PackageNotFoundError
from typing import Any, Dict


MANIFEST_VERSION = "1.0"
SCHEMA_VERSION = "1.0"

REQUIRED_TOOL_VERSIONS: Dict[str, str] = {
    "list_dicom_nodes": "1.0",
    "query_studies": "2.0",
    "query_series": "2.0",
    "move_study": "1.0",
}

OPTIONAL_TOOL_VERSIONS: Dict[str, str] = {
    "get_manifest": "1.0",
    "switch_dicom_node": "1.0",
    "switch_calling_aet": "1.0",
    "verify_connection": "2.0",
    "extract_pdf_text_from_dicom": "1.2",
    "query_patients": "2.0",
    "query_instances": "2.0",
    "download_studies": "1.1",
    "download_series": "1.1",
    "download_instances": "1.1",
    "move_series": "1.0",
    "get_attribute_presets": "1.0",
}


def _package_version() -> str:
    try:
        return metadata.version("dicom-mcp")
    except PackageNotFoundError:
        return "0.0.0"


def build_manifest(server_name: str | None = None) -> Dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "schema_version": SCHEMA_VERSION,
        "server": {
            "name": server_name or "dicom-mcp",
            "version": _package_version(),
        },
        "tools": {
            "required": dict(REQUIRED_TOOL_VERSIONS),
            "optional": dict(OPTIONAL_TOOL_VERSIONS),
        },
    }
