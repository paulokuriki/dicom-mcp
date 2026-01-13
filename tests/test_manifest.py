from dicom_mcp.manifest import (
    MANIFEST_VERSION,
    OPTIONAL_TOOL_VERSIONS,
    REQUIRED_TOOL_VERSIONS,
    SCHEMA_VERSION,
    build_manifest,
)


def test_manifest_contract_versions() -> None:
    manifest = build_manifest("DICOM MCP")
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["schema_version"] == SCHEMA_VERSION


def test_manifest_tools() -> None:
    manifest = build_manifest("DICOM MCP")
    tools = manifest["tools"]
    required = tools["required"]
    optional = tools["optional"]
    for tool_name, version in REQUIRED_TOOL_VERSIONS.items():
        assert required.get(tool_name) == version
    for tool_name, version in OPTIONAL_TOOL_VERSIONS.items():
        assert optional.get(tool_name) == version
