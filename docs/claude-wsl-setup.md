# Claude ↔ WSL MCP Setup Guide
This walkthrough keeps Claude Desktop (Windows) connected to the dicom-mcp server running inside WSL without repeating the earlier troubleshooting.

## 0. Configure WSL2 Networking (Required)
WSL2 uses a separate network namespace by default, which prevents `localhost` from working between Windows and WSL2. Enable **mirrored networking mode** to share the same IP:

1. Create `C:\Users\paulo\.wslconfig` (use notepad from cmd):
   ```cmd
   notepad C:\Users\paulo\.wslconfig
   ```
   Click "Yes" when asked to create a new file.

2. Add this content:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```

3. Shutdown and restart WSL2:
   ```cmd
   wsl --shutdown
   ```

4. Restart your WSL2 Ubuntu and verify `localhost` now works between Windows and WSL2.

**Why this matters:** Without mirrored networking, the MCP server in WSL2 cannot reach services running on Windows (like Orthanc) using `localhost`. The MCP DICOM configuration can now use `localhost` for both Windows and WSL2 services.

## 1. Prepare WSL
```bash
sudo apt update
sudo apt install python3-venv
cd /mnt/c/Users/paulo/Python\ Projects/dicom-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```
- `python3-venv` must match the default `python3` in Ubuntu (3.10/3.11).
- If `.venv` is missing or corrupted, delete it and rerun the commands above.

## 2. Verify the server command
```bash
uv run --with "." python -m dicom_mcp configuration.yaml
```
You should see `DICOM client initialized: …`. This is the exact command Claude will execute.

## 3. Configure Claude Desktop (Windows)
Edit `claude_desktop_config.json`:
```json
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
        "cd /mnt/c/Users/paulo/Python\\ Projects/dicom-mcp && uv run --with '.' python -m dicom_mcp /mnt/c/Users/paulo/Python\\ Projects/dicom-mcp/configuration.yaml"
      ]
    }
  },
  "globalShortcut": "",
  "preferences": {
    "menuBarEnabled": false
  }
}
```
- Replace `Ubuntu` if `wsl -l` shows a different distro name.
- The embedded command mirrors step 2, so Claude launches the MCP server exactly like the manual test.

## 4. Troubleshooting shortcuts
| Symptom | Fix |
| --- | --- |
| `Project virtual environment ... is not a valid Python environment` | Recreate `.venv` with step 1 commands or move it aside so uv stops reusing it. |
| `No module named dicom_mcp` inside UV | Use `uv run --with "." ...` so UV installs the project into its temp env, or activate `.venv` and run `python -m dicom_mcp`. |
| Claude cannot find `wsl.exe` | Use the full path `C:\\Windows\\System32\\wsl.exe` and confirm WSL is enabled in Windows Features. |
| MCP cannot connect to Orthanc/PACS | Ensure WSL2 mirrored networking is enabled (see step 0) and verify with `curl http://localhost:8042/system` from WSL2. |

Once the venv is valid and the command works in WSL, Claude's MCP connection stays up without further tweaks.
