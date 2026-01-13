## Overview

This is my fork of dicom-mcp focused on a simple, practical goal: query DICOM metadata, download exams, and prepare files for anonymization. Credit to Christian Hinge for the original server; I added the download tools, tested with Claude Desktop.

Key additions
- Download tools: `download_studies`, `download_series`, `download_instances`
- Works out‑of‑the‑box with Orthanc; saves to `./downloads` (git‑ignored)
- Keeps upstream features: query, move (C‑MOVE), and PDF text extraction

Repo credit: https://github.com/ChristianHinge/dicom-mcp

## Run it

- Minimal config (configs/dicom.yaml):
```
nodes:
  orthanc:
    host: "localhost"
    port: 4242
    ae_title: "ORTHANC"
    description: "Default Local Orthanc DICOM server"
    aliases: ["local", "dev-orthanc"]

  radiant:
    host: "localhost"
    port: 11112
    ae_title: "RADIANT"
    description: "Radiant Viewer Dicom Node"
    aliases: ["viewer"]

current_node: "orthanc"

calling_aets:
  default:
    ae_title: "MCPSCU"
    description: "Default calling AE"

calling_aet: "default"
query_retrieve_root: "study"

network:
  acse_timeout: 10
  dimse_timeout: 30
  network_timeout: 30
  assoc_timeout: 10
  max_pdu: 16384
  storage_contexts: "all"
  retry:
    max_attempts: 2
    backoff_seconds: 1.0
    backoff_multiplier: 2.0
    backoff_max_seconds: 5.0

storage:
  path: "./downloads"
  retention_days: 30
  dir_permissions: "0o700"
  file_permissions: "0o600"
```

- Start server (dev):
```
uv run --with-editable '.' -m dicom_mcp ../configs/dicom.yaml
```
- If uv caches old code: add `--no-cache` or `--reinstall-package dicom-mcp`.

## Claude Desktop (working JSON)

```
{
  "mcpServers": {
    "DicomMCP": {
      "command": "C:\\Windows\\System32\\wsl.exe",
      "args": [
        "--distribution",
        "Ubuntu",
        "--",
        "bash",
        "-lc",
        "cd '/mnt/c/Users/paulo/Python Projects/dicom-mcp' && uv run --with-editable '.' python -m dicom_mcp '/mnt/c/Users/paulo/Python Projects/configs/dicom.yaml'"
      ]
    }
  },
  "globalShortcut": "",
  "preferences": {
    "menuBarEnabled": false
  }
}
```

WSL tips
- Enable mirrored networking so `localhost` works for both Windows and WSL.
- Use `--with-editable '.'` so your code changes are seen live.

## Tools you can call

- Connection: `list_dicom_nodes`, `switch_dicom_node`, `switch_calling_aet`, `verify_connection`
- Registry: `get_manifest`
- Query: `query_patients`, `query_studies`, `query_series`, `query_instances`, `get_attribute_presets`
- Transfer: `move_study`, `move_series`
- Downloads (this fork): `download_studies`, `download_series`, `download_instances`
- Reports: `extract_pdf_text_from_dicom`

Query tools return structured status metadata:
```json
{
  "success": true,
  "results": [],
  "dicom_statuses": [],
  "warnings": [],
  "error": null
}
```

## Examples

- Find studies in a date range:
```
query_studies(study_date="20230101-20231231")
```

- Filter studies by patient attributes:
```
query_studies(patient_name="*TEST*", patient_sex="O", patient_birth_date="19700101")
```

- Download two studies to `./downloads`:
```
download_studies([
  "1.2.826.0.1.3680043.8.1055.1.20111102150758591.92402465.76095170",
  "1.2.826.0.1.3680043.8.1055.1.20111103111148288.98361414.79379639"
])
```

- Extract text from a DICOM encapsulated PDF:
```
extract_pdf_text_from_dicom(
  study_instance_uid="...",
  series_instance_uid="...",
  sop_instance_uid="...",
  keep_files=True,
)
```
The response includes `pdf_metadata` with page count, PDF size, and whether extracted text was empty.

## Downloads → anonymization

Files are saved to `./downloads` by default. Configure `storage.path` to change the root (legacy `download_directory` is still supported).
`storage.retention_days` cleans old files on startup (set to `0` to disable), and `storage.dir_permissions`/`storage.file_permissions` control permissions.
Downloads are organized as `downloads/studies/<StudyInstanceUID>/series/<SeriesInstanceUID>/...`, each with a `manifest.json` containing UIDs, file paths, timestamps, and source node metadata.
PDF extraction uses temporary files by default; set `keep_files=True` to persist them under `./downloads/reports/<sop_uid>_<timestamp>`.

## Troubleshooting

- If downloads fail with association errors, ensure the server allows C‑GET/C‑STORE back to this AE.
- If uv doesn’t reflect code changes, add `--no-cache` or `--reinstall-package dicom-mcp`.
- On WSL/Windows, enable mirrored networking so `localhost` works across Windows and WSL.

## License & credit

- MIT license (see LICENSE)
- Based on: https://github.com/ChristianHinge/dicom-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
 [![PyPI Version](https://img.shields.io/pypi/v/dicom-mcp.svg)](https://pypi.org/project/dicom-mcp/) [![PyPI Downloads](https://img.shields.io/pypi/dm/dicom-mcp.svg)](https://pypi.org/project/dicom-mcp/)  

The `dicom-mcp` server enables AI assistants to query, read, and move data on DICOM servers (PACS, VNA, etc.). 

<div align="center">

🤝 **[Contribute](#contributing)** •
📝 **[Report Bug](https://github.com/ChristianHinge/dicom-mcp/issues)**  •
📝 **[Blog Post 1](https://www.christianhinge.com/projects/dicom-mcp/)** 

</div>

```text
---------------------------------------------------------------------
🧑‍⚕️ User: "Any significant findings in John Doe's previous CT report?"

🧠 LLM → ⚙️ Tools:
   query_patients → query_studies → query_series → extract_pdf_text_from_dicom

💬 LLM Response: "The report from 2025-03-26 mentions a history of splenomegaly (enlarged spleen)"

🧑‍⚕️ User: "What's the volume of his spleen at the last scan and the scan today?"

🧠 LLM → ⚙️ Tools:
   (query_studies → query_series → move_series → query_series → extract_pdf_text_from_dicom) x2
   (The move_series tool sends the latest CT to a DICOM segmentation node, which returns volume PDF report)

💬 LLM Response: "last year 2024-03-26: 412cm³, today 2025-04-10: 350cm³"
---------------------------------------------------------------------
```


## ✨ Core Capabilities

`dicom-mcp` provides tools to:

* **🔍 Query Metadata**: Search for patients, studies, series, and instances using various criteria.
* **📄 Read DICOM Reports (PDF)**: Retrieve DICOM instances containing encapsulated PDFs (e.g., clinical reports) and extract the text content.
* **➡️ Send DICOM Images**: Send series or studies to other DICOM destinations, e.g. AI endpoints for image segmentation, classification, etc.
* **⚙️ Utilities**: Manage connections and understand query options.

## 🚀 Quick Start
### 📥 Installation
Install using uv:

```bash
uv tool install dicom-mcp
```

Or by cloning the repository:

```bash
# Clone and set up development environment
git clone https://github.com/ChristianHinge/dicom-mcp
cd dicom-mcp

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install with dev dependencies
uv pip install -e ".[dev]"
```


### ⚙️ Configuration

`dicom-mcp` requires a YAML configuration file (`config.yaml` or similar) defining DICOM nodes and calling AE titles. Adapt the configuration or keep as is for compatibility with the sample ORTHANC  Server.

```yaml
nodes:
  main:
    host: "localhost"
    port: 4242 
    ae_title: "ORTHANC"
    description: "Local Orthanc DICOM server"
    aliases: ["local", "dev-orthanc"]

current_node: "main"

calling_aets:
  default:
    ae_title: "MCPSCU"
    description: "Default calling AE"

calling_aet: "default"
query_retrieve_root: "study"

network:
  acse_timeout: 10
  dimse_timeout: 30
  network_timeout: 30
  assoc_timeout: 10
  max_pdu: 16384
  storage_contexts: "all"
  retry:
    max_attempts: 2
    backoff_seconds: 1.0
    backoff_multiplier: 2.0
    backoff_max_seconds: 5.0

storage:
  path: "./downloads"
  retention_days: 30
  dir_permissions: "0o700"
  file_permissions: "0o600"
```
Notes:
- `calling_aet` can be a name, alias, or AE title defined in `calling_aets`.
- `query_retrieve_root` accepts `study` or `patient`.
- `network.storage_contexts` supports `all` (default) or `core` for common modalities.
> [!WARNING]
DICOM-MCP is not meant for clinical use, and should not be connected with live hospital databases or databases with patient-sensitive data. Doing so could lead to both loss of patient data, and leakage of patient data onto the internet. DICOM-MCP can be used with locally hosted open-weight LLMs for complete data privacy. 

### (Optional) Sample ORTHANC server
If you don't have a DICOM server available, you can run a local ORTHANC server using Docker:

Clone the repository and install test dependencies:

```bash
uv pip install -e ".[dev]"
```

Start Orthanc and run tests:

```bash
cd tests
docker compose up -d
cd ..
uv run pytest -m integration  # uploads dummy pdf data to ORTHANC server
```

UI at [http://localhost:8042](http://localhost:8042)

### 🔌 MCP Integration

Add to your client configuration (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dicom": {
      "command": "uv",
      "args": ["tool","dicom-mcp", "/path/to/your_config.yaml"]
    }
  }
}
```

For development:

```json
{
    "mcpServers": {
        "arxiv-mcp-server": {
            "command": "uv",
            "args": [
                "--directory",
                "path/to/cloned/dicom-mcp",
                "run",
                "dicom-mcp",
                "/path/to/your_config.yaml"
            ]
        }
    }
}
```


## 🛠️ Tools Overview

`dicom-mcp` provides five categories of tools for interaction with DICOM servers and DICOM data. 

### 🔍 Query Metadata

* **`query_patients`**: Search for patients based on criteria like name, ID, or birth date.
* **`query_studies`**: Find studies using patient ID, date, modality, description, accession number, or Study UID.
* **`query_series`**: Locate series within a specific study using modality, series number/description, or Series UID.
* **`query_instances`**: Find individual instances (images/objects) within a series using instance number or SOP Instance UID
### 📄 Read DICOM Reports (PDF)

* **`extract_pdf_text_from_dicom`**: Retrieve a specific DICOM instance containing an encapsulated PDF and extract its text content.

### ➡️ Send DICOM Images

* **`move_series`**: Send a specific DICOM series to another configured DICOM node using C-MOVE.
* **`move_study`**: Send an entire DICOM study to another configured DICOM node using C-MOVE.

### 📥 Downloads

* **`download_studies`**: Download one or more studies to the local storage root.
* **`download_series`**: Download one or more series within a study.
* **`download_instances`**: Download specific instances within a series.

### ⚙️ Utilities

* **`list_dicom_nodes`**: Show the currently active DICOM node, calling AE title, and list all configured nodes.
* **`switch_dicom_node`**: Change the active DICOM node for subsequent operations.
* **`switch_calling_aet`**: Change the calling AE title used for new associations.
* **`verify_connection`**: Test the DICOM network connection to the currently active node using C-ECHO.
* **`get_attribute_presets`**: List the available levels of detail (minimal, standard, extended) for metadata query results.<p>
* **`get_manifest`**: Return the MCP tool contract manifest (required/optional tool versions).


### Example interaction
The tools can be chained together to answer complex questions:


<div align="center">
<img src="images/example.png" alt="My Awesome Diagram" width="700">
</div>


## 📈 Contributing
### Running Tests

Unit tests run without Orthanc; integration tests require a running Orthanc DICOM server. You can use Docker:

```bash
# Navigate to the directory containing docker-compose.yml (e.g., tests/)
cd tests
docker compose up -d
```

Run unit tests using uv:

```bash
# From the project root directory
uv run pytest -m "not integration"
```

Run integration tests using uv:

```bash
# From the project root directory
uv run pytest -m integration
```

Stop the Orthanc container:

```bash
cd tests
docker compose down
```

### Debugging

Use the MCP Inspector for debugging the server communication:

```bash
npx @modelcontextprotocol/inspector uv run dicom-mcp /path/to/your_config.yaml --transport stdio
```

### Logging

Set `LOG_LEVEL` to control verbosity (e.g., `DEBUG`, `INFO`, `WARNING`):

```bash
LOG_LEVEL=DEBUG uv run dicom-mcp /path/to/your_config.yaml --transport stdio
```

### Linting, formatting, type checking

```bash
uv run ruff check .
uv run ruff format .
uv run pyright
```

### Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## 🙏 Acknowledgments

* Built using [pynetdicom](https://github.com/pydicom/pynetdicom)
* Uses [pypdf](https://pypi.org/project/pypdf/) for PDF text extraction
