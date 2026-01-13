import os
import tempfile

import pytest

from dicom_mcp.dicom_client import DicomClient
from dicom_mcp.errors import StorageSecurityError


def test_sanitize_filename_replaces_separators_and_truncates() -> None:
    sample = f"abc{os.sep}def"
    if os.altsep:
        sample = f"{sample}{os.altsep}ghi"
    sanitized = DicomClient._sanitize_filename(sample)
    assert os.sep not in sanitized
    if os.altsep:
        assert os.altsep not in sanitized
    assert sanitized.startswith("abc_def")

    long_name = "a" * 256
    truncated = DicomClient._sanitize_filename(long_name, max_length=64)
    assert len(truncated) == 64

    assert DicomClient._sanitize_filename("") == "unknown"


def test_ensure_safe_path_rejects_traversal() -> None:
    with tempfile.TemporaryDirectory() as base_dir:
        unsafe = os.path.join(base_dir, "..", "outside")
        with pytest.raises(StorageSecurityError):
            DicomClient._ensure_safe_path(base_dir, unsafe)


def test_prepare_directory_applies_permissions() -> None:
    if os.name == "nt":
        pytest.skip("POSIX permissions are not reliably enforced on Windows")
    with tempfile.TemporaryDirectory() as base_dir:
        target_dir = os.path.join(base_dir, "downloads")
        created = DicomClient._prepare_directory(target_dir, dir_permissions="0o700")
        mode = os.stat(created).st_mode & 0o777
        assert mode == 0o700
