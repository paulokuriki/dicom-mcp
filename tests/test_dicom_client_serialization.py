import json

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.valuerep import PersonName

from dicom_mcp.dicom_client import DicomClient


def test_dataset_to_dict_is_json_serializable() -> None:
    ds = Dataset()
    ds.PatientName = PersonName("DOE^JANE")
    ds.OtherPatientNames = ["DOE^ALICE", "DOE^BOB"]
    ds.SeriesNumber = 7
    ds.StudyDate = "20240101"
    ds.StudyInstanceUID = "1.2.3.4"

    nested = Dataset()
    nested.Modality = "CT"
    nested.SeriesDescription = "Example Series"
    ds.ReferencedSeriesSequence = Sequence([nested])

    result = DicomClient._dataset_to_dict(ds)

    json.dumps(result)
    assert result["PatientName"] == "DOE^JANE"
    assert result["OtherPatientNames"] == ["DOE^ALICE", "DOE^BOB"]
    assert result["ReferencedSeriesSequence"][0]["Modality"] == "CT"
    assert str(result["SeriesNumber"]) == "7"
    assert result["StudyInstanceUID"] == "1.2.3.4"
