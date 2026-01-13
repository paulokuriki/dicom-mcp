"""
Prompt registrations for the MCP server.
"""

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register MCP prompts."""

    @mcp.prompt()
    def dicom_query_guide() -> str:
        """Prompt for guiding users on how to query DICOM data."""
        return """
DICOM Query Guide

This DICOM Model Context Protocol (MCP) server allows you to interact with medical imaging data from DICOM nodes.

## Node Management
1. View available DICOM nodes and calling AE titles:
   ```
   list_dicom_nodes()
   ```

2. Switch to a different node:
   ```
   switch_dicom_node(node_name="research")
   ```

3. Switch to a different calling AE title:
   ```
   switch_calling_aet(aet_name="modality")
   ```

4. Verify the connection:
   ```
   verify_connection()
   ```

## Search Queries
For flexible search operations:

1. Search for patients:
   ```
   query_patients(name_pattern="SMITH*")
   ```

2. Search for studies:
   ```
   query_studies(patient_id="12345678", study_date="20230101-20231231")
   ```

3. Search for series:
   ```
   query_series(study_instance_uid="1.2.840.10008.5.1.4.1.1.2.1.1", modality="CT")
   ```

4. Search for instances:
   ```
   query_instances(series_instance_uid="1.2.840.10008.5.1.4.1.1.2.1.2")
   ```

Query tools return a structured response:
```
{
  "success": true,
  "results": [],
  "dicom_statuses": [],
  "warnings": [],
  "error": null
}
```

## Attribute Presets
For all queries, you can specify an attribute preset:
- `minimal`: Basic identifiers only
- `standard`: Common clinical attributes
- `extended`: Comprehensive information

Example:
```
query_studies(patient_id="12345678", attribute_preset="extended")
```

You can also customize attributes:
```
query_studies(
    patient_id="12345678",
    additional_attributes=["StudyComments"],
    exclude_attributes=["AccessionNumber"]
)
```

To view available attribute presets:
```
get_attribute_presets()
```

## Study/Series Transfer
Move DICOM objects to a configured destination DICOM node:
```
# Move a whole study
move_study(destination_node="radiant", study_instance_uid="1.2.840...")

# Move a single series
move_series(destination_node="radiant", series_instance_uid="1.2.840...")
```
"""
