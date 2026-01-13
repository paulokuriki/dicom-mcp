"""
DICOM move operations.
"""

import logging
from typing import Any, Dict

from pydicom.dataset import Dataset


class DicomClientMoveMixin:
    """C-MOVE related operations."""

    def _execute_move(self, dataset: Dataset, destination_ae: str, uid_type: str) -> dict:
        """Execute a C-MOVE request for a prepared dataset."""
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)

        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                "completed": 0,
                "failed": 0,
                "warning": 0,
            }

        result = {
            "success": False,
            "message": "C-MOVE operation failed",
            "completed": 0,
            "failed": 0,
            "warning": 0,
        }

        try:
            op_label = f"C-MOVE {uid_type}" if uid_type else "C-MOVE"
            self._log_association_contexts(assoc, op_label)
            responses = assoc.send_c_move(
                dataset,
                destination_ae,
                self._move_model,
            )

            for (status, identifier) in responses:
                if status:
                    # Record the sub-operation counts if available
                    if hasattr(status, "NumberOfCompletedSuboperations"):
                        result["completed"] = status.NumberOfCompletedSuboperations
                    if hasattr(status, "NumberOfFailedSuboperations"):
                        result["failed"] = status.NumberOfFailedSuboperations
                    if hasattr(status, "NumberOfWarningSuboperations"):
                        result["warning"] = status.NumberOfWarningSuboperations

                    # Check the status code
                    if status.Status == 0x0000:  # Success
                        result["success"] = True
                        result["message"] = "C-MOVE operation completed successfully"
                    elif status.Status == 0x0001 or status.Status == 0xB000:  # Success with warnings
                        result["success"] = True
                        result["message"] = "C-MOVE operation completed with warnings or failures"
                    elif status.Status == 0xA801:  # Refused: Move destination unknown
                        result["message"] = (
                            f"C-MOVE refused: Destination '{destination_ae}' unknown"
                        )
                    else:
                        result["message"] = f"C-MOVE failed with status 0x{status.Status:04X}"

                    # If we got a dataset with an error comment, add it
                    if identifier and hasattr(identifier, "ErrorComment"):
                        result["message"] += f": {identifier.ErrorComment}"

        finally:
            # Always release the association
            assoc.release()

        return result

    def move_series(
        self,
        destination_ae: str,
        series_instance_uid: str,
        study_instance_uid: str | None = None,
    ) -> dict:
        """Move a DICOM series to another DICOM node using C-MOVE."""
        self._log_event(
            logging.INFO,
            "move_series",
            destination_ae=destination_ae,
            series_instance_uid=series_instance_uid,
            study_instance_uid=study_instance_uid,
        )
        # Create query dataset for series level
        ds = Dataset()
        ds.QueryRetrieveLevel = "SERIES"
        ds.SeriesInstanceUID = series_instance_uid
        if study_instance_uid:
            ds.StudyInstanceUID = study_instance_uid

        return self._execute_move(ds, destination_ae, "series")

    def move_study(self, destination_ae: str, study_instance_uid: str) -> dict:
        """Move a DICOM study to another DICOM node using C-MOVE."""
        self._log_event(
            logging.INFO,
            "move_study",
            destination_ae=destination_ae,
            study_instance_uid=study_instance_uid,
        )
        # Create query dataset for study level
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_instance_uid

        return self._execute_move(ds, destination_ae, "study")

    def transfer_study_via_c_move(
        self,
        study_instance_uid: str,
        destination_ae_title: str,
    ) -> Dict[str, Any]:
        """Use C-MOVE to transfer a study to another DICOM node."""
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_instance_uid

        # Associate
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)

        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with {self.host}:{self.port}",
            }

        try:
            self._log_association_contexts(assoc, "C-MOVE")
            responses = assoc.send_c_move(
                ds,
                move_aet=destination_ae_title,
                query_model=self._move_model,
            )

            status_list = []
            for (status, identifier) in responses:
                if status:
                    status_list.append(f"Status: 0x{status.Status:04X}")
                else:
                    status_list.append("No response status")

            return {
                "success": True,
                "message": "C-MOVE request completed",
                "statuses": status_list,
            }
        finally:
            assoc.release()
