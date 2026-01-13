import os
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

from dicom_mcp.config import DicomConfiguration, NetworkConfig, StorageConfig
from dicom_mcp.dicom_client import DicomClient
from dicom_mcp.server import cleanup_old_files


MINIMAL_NODES = {
    "test": {
        "host": "localhost",
        "port": 11112,
        "ae_title": "TEST",
        "description": "Test node",
    }
}


class TestStorageSecurity:
    def test_storage_config_defaults(self) -> None:
        config = StorageConfig()
        assert config.path == "./downloads"
        assert config.retention_days == 30
        assert config.dir_permissions == "0o700"
        assert config.file_permissions == "0o600"

    def test_network_config_defaults(self) -> None:
        config = NetworkConfig()
        assert config.acse_timeout == 10
        assert config.dimse_timeout == 30
        assert config.network_timeout == 30
        assert config.assoc_timeout == 10
        assert config.max_pdu == 16384
        assert config.storage_contexts == "all"
        assert config.retry.max_attempts == 2
        assert config.retry.backoff_seconds == 1.0
        assert config.retry.backoff_multiplier == 2.0
        assert config.retry.backoff_max_seconds == 5.0

    def test_dicom_config_storage(self) -> None:
        config = DicomConfiguration(
            nodes=MINIMAL_NODES,
            current_node="test",
            calling_aet="TEST",
            storage=StorageConfig(path="/tmp/test", retention_days=7),
        )
        assert config.storage.path == "/tmp/test"
        assert config.storage.retention_days == 7
        assert config.storage.dir_permissions == "0o700"
        assert config.download_path == "/tmp/test"

    def test_dicom_config_legacy_precedence(self) -> None:
        config = DicomConfiguration(
            nodes=MINIMAL_NODES,
            current_node="test",
            calling_aet="TEST",
            download_directory="/legacy/path",
            storage=StorageConfig(path="/new/path"),
        )
        assert config.download_path == "/legacy/path"

    def test_validate_safe_path(self) -> None:
        base = os.path.abspath("/base/dir")
        safe_file = os.path.join(base, "file.dcm")
        safe_subdir = os.path.join(base, "subdir", "file.dcm")

        assert DicomClient._validate_safe_path(base, safe_file)
        assert DicomClient._validate_safe_path(base, safe_subdir)

        unsafe_absolute = "/etc/passwd"
        assert not DicomClient._validate_safe_path(base, unsafe_absolute)

        unsafe_relative = os.path.join(base, "..", "outside.dcm")
        assert not DicomClient._validate_safe_path(base, unsafe_relative)

    def test_cleanup_old_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            studies_path = Path(temp_dir) / "studies"
            studies_path.mkdir(parents=True, exist_ok=True)

            new_file = studies_path / "new.dcm"
            new_file.touch()

            old_file = studies_path / "old.dcm"
            old_file.touch()

            old_time = time.time() - (31 * 86400)
            os.utime(old_file, (old_time, old_time))

            # Pass root_dir (temp_dir), not the studies subdirectory
            count = cleanup_old_files(temp_dir, 30)

            assert count == 1
            assert new_file.exists(), "New file should be preserved"
            assert not old_file.exists(), "Old file should be deleted"

    @patch("os.chmod")
    def test_apply_permissions(self, mock_chmod) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            DicomClient._apply_permissions(tmp.name, "0o600")
            mock_chmod.assert_called_with(tmp.name, 0o600)

            DicomClient._apply_permissions(tmp.name, "0o644")
            mock_chmod.assert_called_with(tmp.name, 0o644)
