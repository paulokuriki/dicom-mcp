# DICOM MCP Test Environment

A minimal test environment for testing DICOM Model Context Protocol server with Orthanc DICOM server.

## Setup

1. Start Orthanc DICOM server with Docker Compose:

```bash
docker compose up -d
```

2. Install dev dependencies from the repo root:

```bash
uv pip install -e ".[dev]"
```

## Running Tests

Run unit tests using pytest:

```bash
uv run pytest -m "not integration"
```

Run integration tests using pytest:

```bash
uv run pytest -m integration
```

## Test Environment

### Orthanc DICOM Server
- Default URL: http://localhost:8042
- Default DICOM port: 4242

### Configuration

The test environment uses these environment variables (with defaults):

- `ORTHANC_HOST`: Hostname of Orthanc (default: "localhost")
- `ORTHANC_PORT`: DICOM port of Orthanc (default: "4242")
- `ORTHANC_WEB_PORT`: Web UI port of Orthanc (default: "8042")
- `ORTHANC_AET`: AE Title of Orthanc (default: "ORTHANC")

For the DICOM MCP server:
- `DICOM_HOST`: Connection target (defaults to ORTHANC_HOST) 
- `DICOM_PORT`: Connection port (defaults to ORTHANC_PORT)
- `DICOM_AE_TITLE`: Target AE title (defaults to ORTHANC_AET)

## What the Tests Do

1. Verify Orthanc is running
2. Perform a DICOM C-ECHO verification
3. Upload a minimal test DICOM dataset
4. Test the DICOM MCP server tools:
   - verify_connection
   - query_patients
   - query_studies
   - query_series
   - query_instances
   - get_attribute_presets
   - download_studies
   - download_series
   - download_instances
   - extract_pdf_text_from_dicom
   - move_series
   - move_study
   - get_manifest
