import tempfile
from pathlib import Path

import pytest

from dicom_mcp.dicom_client import DicomClient
from tests.test_dicom_mcp import (
    _get_test_series_uid,
    _get_test_study_uid,
    dicom_config,
    dicom_client,
    upload_test_data,
)

pytestmark = pytest.mark.integration


def _get_test_sop_uid(dicom_client: DicomClient, series_uid: str) -> str:
    result = dicom_client.query_instance(series_instance_uid=series_uid)
    assert result["success"] is True
    instances = result["results"]
    assert instances, "No instances found for download"
    return instances[0]["SOPInstanceUID"]


def test_download_instances_single_sop(dicom_client, upload_test_data) -> None:
    study_uid = _get_test_study_uid(dicom_client)
    series_uid = _get_test_series_uid(dicom_client)

    name_query = dicom_client.query_study(patient_name="*TEST*")
    assert name_query["success"] is True
    assert name_query["results"], "No studies found via name query"

    sop_uid = _get_test_sop_uid(dicom_client, series_uid)

    with tempfile.TemporaryDirectory() as download_root:
        result = dicom_client.download_instances(
            study_instance_uid=study_uid,
            series_instance_uid=series_uid,
            sop_instance_uids=[sop_uid],
            download_root=download_root,
        )

        assert result["success"] is True
        assert result["files_downloaded"] == 1
        assert result["items"]
        file_path = result["items"][0]["files"][0]
        assert file_path
        assert Path(file_path).exists()
