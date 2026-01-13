"""
DICOM query operations.
"""

import logging
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from pydicom.dataset import Dataset
from pydicom.datadict import dictionary_VR, tag_for_keyword
from pydicom.multival import MultiValue
from pydicom.sequence import Sequence
from pynetdicom.sop_class import PatientRootQueryRetrieveInformationModelFind

from .attributes import get_attributes_for_level
from .errors import DicomAssociationError

class DicomClientQueryMixin:
    """Query-related DICOM operations."""

    @staticmethod
    def _set_query_attribute(dataset: Dataset, keyword: str) -> None:
        if hasattr(dataset, keyword):
            return
        tag = tag_for_keyword(keyword)
        if tag is None:
            setattr(dataset, keyword, "")
            return
        vr = dictionary_VR(tag)
        # Empty elements request return keys; sequences need an empty Sequence value.
        if vr == "SQ":
            setattr(dataset, keyword, Sequence([]))
        else:
            setattr(dataset, keyword, "")

    def find(
        self,
        query_dataset: Dataset,
        query_model=None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute a C-FIND request."""
        if query_model is None:
            query_model = self._find_model
        if limit is not None and limit <= 0:
            limit = None

        def _attempt() -> Dict[str, Any]:
            assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)
            if not assoc.is_established:
                raise DicomAssociationError(
                    f"Failed to associate with DICOM node at {self.host}:{self.port} "
                    f"(Called AE: {self.called_aet}, Calling AE: {self.calling_aet})"
                )
            self._log_association_contexts(assoc, "C-FIND")

            results: List[Dict[str, Any]] = []
            dicom_statuses: List[Dict[str, Any]] = []
            warnings: List[Dict[str, str]] = []
            error: Optional[Dict[str, str]] = None
            pending_statuses = {0xFF00, 0xFF01}
            limit_reached = False
            final_category: Optional[str] = None
            final_status_code: Optional[int] = None

            try:
                # Send C-FIND request
                msg_id = self._get_next_message_id(assoc)
                responses, msg_id = self._send_c_find(assoc, query_dataset, query_model, msg_id)

                for (status, dataset) in responses:
                    if not status or not hasattr(status, "Status"):
                        continue
                    try:
                        status_code = int(status.Status)
                    except Exception:
                        continue
                    category = self._status_category(status_code)
                    status_entry = {
                        "code": f"0x{status_code:04X}",
                        "category": category,
                    }
                    error_comment = getattr(status, "ErrorComment", None)
                    if error_comment:
                        status_entry["error_comment"] = str(error_comment)
                    offending_element = getattr(status, "OffendingElement", None)
                    if offending_element:
                        status_entry["offending_element"] = str(offending_element)
                    if category != "pending" or error_comment:
                        status_entry["message"] = self._status_message(status, status_code, category)
                    dicom_statuses.append(status_entry)

                    if status_code in pending_statuses:
                        if not limit_reached and dataset:
                            results.append(self._dataset_to_dict(dataset))
                            if limit is not None and len(results) >= limit:
                                limit_reached = True
                                self._send_c_cancel(assoc, msg_id)
                        continue
                    # Final response (success, cancel, warning, or failure).
                    final_category = category
                    final_status_code = status_code
                    if category == "failure" and error is None:
                        error = {
                            "code": f"0x{status_code:04X}",
                            "message": self._status_message(status, status_code, category),
                        }
                    elif category in {"warning", "cancel"}:
                        warnings.append(
                            {
                                "code": f"0x{status_code:04X}",
                                "message": self._status_message(status, status_code, category),
                            }
                        )
                    break
            finally:
                # Always release the association
                assoc.release()

            if final_category is None:
                error = error or {
                    "code": "",
                    "message": "No final DICOM status received",
                }
                success = False
            else:
                success = final_category != "failure"
                if final_category == "failure" and error is None:
                    error = {
                        "code": f"0x{final_status_code:04X}" if final_status_code is not None else "",
                        "message": "DICOM failure status",
                    }

            return {
                "success": success,
                "results": results,
                "dicom_statuses": dicom_statuses,
                "warnings": warnings,
                "error": error,
            }

        return self._with_retry("C-FIND", _attempt)

    def query_patient(
        self,
        patient_id: str = None,
        name_pattern: str = None,
        birth_date: str = None,
        attribute_preset: str = "standard",
        additional_attrs: List[str] = None,
        exclude_attrs: List[str] = None,
    ) -> Dict[str, Any]:
        """Query for patients matching criteria."""
        self._log_event(logging.INFO, "query_patients")
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = "PATIENT"

        # Add query parameters if provided
        if patient_id:
            ds.PatientID = patient_id

        if name_pattern:
            ds.PatientName = name_pattern

        if birth_date:
            ds.PatientBirthDate = birth_date

        # Add attributes based on preset
        attrs = get_attributes_for_level("patient", attribute_preset, additional_attrs, exclude_attrs)
        for attr in attrs:
            self._set_query_attribute(ds, attr)

        # Execute query
        return self.find(ds, PatientRootQueryRetrieveInformationModelFind)

    def query_study(
        self,
        patient_id: str = None,
        patient_name: str = None,
        patient_sex: str = None,
        patient_birth_date: str = None,
        study_date: str = None,
        modality: str = None,
        study_description: str = None,
        accession_number: str = None,
        study_instance_uid: str = None,
        limit: Optional[int] = None,
        attribute_preset: str = "standard",
        additional_attrs: List[str] = None,
        exclude_attrs: List[str] = None,
    ) -> Dict[str, Any]:
        """Query for studies matching criteria."""
        self._log_event(
            logging.INFO,
            "query_studies",
            study_instance_uid=study_instance_uid,
        )
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"

        # Add query parameters if provided
        if patient_id:
            ds.PatientID = patient_id

        if patient_name:
            ds.PatientName = patient_name

        if patient_sex:
            ds.PatientSex = patient_sex

        if patient_birth_date:
            ds.PatientBirthDate = patient_birth_date

        if study_date:
            ds.StudyDate = study_date

        if modality:
            ds.ModalitiesInStudy = modality

        if study_description:
            ds.StudyDescription = study_description

        if accession_number:
            ds.AccessionNumber = accession_number

        if study_instance_uid:
            ds.StudyInstanceUID = study_instance_uid

        # Add attributes based on preset
        attrs = get_attributes_for_level("study", attribute_preset, additional_attrs, exclude_attrs)
        for attr in attrs:
            self._set_query_attribute(ds, attr)

        # Execute query
        return self.find(ds, self._find_model, limit=limit)

    def query_series(
        self,
        study_instance_uid: str,
        series_instance_uid: str = None,
        modality: str = None,
        series_number: str = None,
        series_description: str = None,
        limit: Optional[int] = None,
        attribute_preset: str = "standard",
        additional_attrs: List[str] = None,
        exclude_attrs: List[str] = None,
    ) -> Dict[str, Any]:
        """Query for series matching criteria."""
        self._log_event(
            logging.INFO,
            "query_series",
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
        )
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = "SERIES"
        ds.StudyInstanceUID = study_instance_uid

        # Add query parameters if provided
        if series_instance_uid:
            ds.SeriesInstanceUID = series_instance_uid

        if modality:
            ds.Modality = modality

        if series_number:
            ds.SeriesNumber = series_number

        if series_description:
            ds.SeriesDescription = series_description

        # Add attributes based on preset
        attrs = get_attributes_for_level("series", attribute_preset, additional_attrs, exclude_attrs)
        for attr in attrs:
            self._set_query_attribute(ds, attr)

        # Execute query
        return self.find(ds, self._find_model, limit=limit)

    def query_instance(
        self,
        series_instance_uid: str,
        sop_instance_uid: str = None,
        instance_number: str = None,
        attribute_preset: str = "standard",
        additional_attrs: List[str] = None,
        exclude_attrs: List[str] = None,
    ) -> Dict[str, Any]:
        """Query for instances matching criteria."""
        self._log_event(
            logging.INFO,
            "query_instances",
            series_instance_uid=series_instance_uid,
            sop_instance_uid=sop_instance_uid,
        )
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = "IMAGE"
        ds.SeriesInstanceUID = series_instance_uid

        # Add query parameters if provided
        if sop_instance_uid:
            ds.SOPInstanceUID = sop_instance_uid

        if instance_number:
            ds.InstanceNumber = instance_number

        # Add attributes based on preset
        attrs = get_attributes_for_level("instance", attribute_preset, additional_attrs, exclude_attrs)
        for attr in attrs:
            self._set_query_attribute(ds, attr)

        # Execute query
        return self.find(ds, self._find_model)

    @staticmethod
    def _dataset_to_dict(dataset: Dataset) -> Dict[str, Any]:
        """Convert a DICOM dataset to a dictionary."""
        if hasattr(dataset, "is_empty") and dataset.is_empty():
            return {}

        result: Dict[str, Any] = {}
        for elem in dataset:
            if elem.VR == "SQ":
                # Handle sequences
                result[elem.keyword] = [
                    DicomClientQueryMixin._dataset_to_dict(item) for item in elem.value
                ]
            else:
                # Handle regular elements
                if hasattr(elem, "keyword"):
                    try:
                        if elem.VM > 1:
                            # Multiple values
                            result[elem.keyword] = [
                                DicomClientQueryMixin._json_safe_value(item)
                                for item in elem.value
                            ]
                        else:
                            # Single value
                            result[elem.keyword] = DicomClientQueryMixin._json_safe_value(elem.value)
                    except Exception:
                        # Fall back to string representation
                        result[elem.keyword] = str(elem.value)

        return result

    @staticmethod
    def _json_safe_value(value: Any) -> Any:
        """Convert DICOM values into JSON-serializable Python types."""
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, (bytes, bytearray, memoryview)):
            try:
                return bytes(value).decode("utf-8")
            except Exception:
                return bytes(value).hex()

        if isinstance(value, Dataset):
            return DicomClientQueryMixin._dataset_to_dict(value)

        if isinstance(value, Sequence):
            return [DicomClientQueryMixin._dataset_to_dict(item) for item in value]

        if isinstance(value, MultiValue):
            return [DicomClientQueryMixin._json_safe_value(item) for item in value]

        if isinstance(value, Mapping):
            return {
                str(key): DicomClientQueryMixin._json_safe_value(val) for key, val in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [DicomClientQueryMixin._json_safe_value(item) for item in value]

        module_name = value.__class__.__module__
        if module_name.startswith("pydicom.valuerep") or module_name.startswith("pydicom.uid"):
            return str(value)

        if hasattr(value, "tolist"):
            try:
                return DicomClientQueryMixin._json_safe_value(value.tolist())
            except Exception:
                pass

        return str(value)
