"""
PDF extraction helpers for DICOM instances.
"""

import logging
import os
import tempfile
from contextlib import nullcontext
from typing import Any, Dict, Optional

from pydicom.dataset import Dataset, FileMetaDataset
from pynetdicom import build_role, evt
from pynetdicom.sop_class import EncapsulatedPDFStorage

class DicomClientPdfMixin:
    """Extract text from encapsulated PDF instances."""

    def extract_pdf_text_from_dicom(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        sop_instance_uid: str,
        keep_files: bool = False,
        output_dir: Optional[str] = None,
        file_permissions: str = "0o600",
        dir_permissions: str = "0o700",
    ) -> Dict[str, Any]:
        """Retrieve a DICOM instance with encapsulated PDF and extract its text content."""
        self._log_event(
            logging.INFO,
            "extract_pdf_text_from_dicom",
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
            sop_instance_uid=sop_instance_uid,
            keep_files=keep_files,
        )
        if output_dir:
            temp_ctx = nullcontext(self._prepare_directory(output_dir, dir_permissions))
            keep_files = True
        elif keep_files:
            temp_dir = tempfile.mkdtemp()
            self._apply_permissions(temp_dir, dir_permissions)
            temp_ctx = nullcontext(temp_dir)
        else:
            temp_ctx = tempfile.TemporaryDirectory()

        with temp_ctx as temp_dir:
            self._apply_permissions(temp_dir, dir_permissions)

            # Create dataset for C-GET query
            ds = Dataset()
            ds.QueryRetrieveLevel = "IMAGE"
            ds.StudyInstanceUID = study_instance_uid
            ds.SeriesInstanceUID = series_instance_uid
            ds.SOPInstanceUID = sop_instance_uid

            # Define a handler for C-STORE operations during C-GET
            received_files = []
            pdf_metadata = {
                "page_count": 0,
                "pdf_size_bytes": 0,
                "text_empty": True,
                "text_length": 0,
            }

            def handle_store(event):
                """Handle C-STORE operations during C-GET"""
                ds = event.dataset
                sop_instance = ds.SOPInstanceUID if hasattr(ds, "SOPInstanceUID") else "unknown"
                sop_instance = self._sanitize_filename(sop_instance)

                # Ensure we have file meta information
                if not hasattr(ds, "file_meta") or not hasattr(ds.file_meta, "TransferSyntaxUID"):
                    if not hasattr(ds, "file_meta"):
                        ds.file_meta = FileMetaDataset()

                    if event.context.transfer_syntax:
                        ds.file_meta.TransferSyntaxUID = event.context.transfer_syntax
                    else:
                        ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"

                    if not hasattr(ds.file_meta, "MediaStorageSOPClassUID") and hasattr(ds, "SOPClassUID"):
                        ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID

                    if not hasattr(ds.file_meta, "MediaStorageSOPInstanceUID") and hasattr(
                        ds, "SOPInstanceUID"
                    ):
                        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

                # Save the dataset to file
                file_path = os.path.join(temp_dir, f"{sop_instance}.dcm")
                self._save_dataset_atomic(ds, file_path, file_permissions)
                received_files.append(file_path)

                return 0x0000  # Success

            # Define event handlers - using the proper format for pynetdicom
            handlers = [(evt.EVT_C_STORE, handle_store)]

            # Create an SCP/SCU Role Selection Negotiation item for PDF Storage
            role = build_role(EncapsulatedPDFStorage, scp_role=True)

            # Associate with the DICOM node, providing the event handlers during association
            assoc = self.ae.associate(
                self.host,
                self.port,
                ae_title=self.called_aet,
                evt_handlers=handlers,
                ext_neg=[role],
            )

            if not assoc.is_established:
                return {
                    "success": False,
                    "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                    "text_content": "",
                    "file_path": "",
                    "pdf_metadata": pdf_metadata,
                }

            success = False
            message = "C-GET operation failed"
            extracted_text = ""

            try:
                self._log_association_contexts(assoc, "C-GET")
                # Send C-GET request - without evt_handlers parameter since we provided them during association
                responses = assoc.send_c_get(ds, self._get_model)

                for (status, dataset) in responses:
                    if status:
                        status_int = status.Status if hasattr(status, "Status") else 0

                        if status_int == 0x0000:  # Success
                            success = True
                            message = "C-GET operation completed successfully"
                        elif status_int == 0xFF00:  # Pending
                            success = True  # Still processing
                            message = "C-GET operation in progress"
            finally:
                # Always release the association
                assoc.release()

            # Process received files
            if received_files:
                dicom_file = received_files[0]

                # Read the DICOM file
                from pydicom import dcmread

                ds = dcmread(dicom_file)

                # Check if it's an encapsulated PDF
                if (
                    hasattr(ds, "SOPClassUID")
                    and ds.SOPClassUID == "1.2.840.10008.5.1.4.1.1.104.1"
                ):

                    # Extract the PDF data
                    pdf_data = ds.EncapsulatedDocument
                    pdf_metadata["pdf_size_bytes"] = len(pdf_data) if pdf_data else 0

                    # Write to a temporary file
                    pdf_path = os.path.join(temp_dir, "extracted.pdf")
                    with open(pdf_path, "wb") as pdf_file:
                        pdf_file.write(pdf_data)
                    self._apply_permissions(pdf_path, file_permissions)

                    from pypdf import PdfReader

                    # Extract text from the PDF
                    with open(pdf_path, "rb") as pdf_file:
                        pdf_reader = PdfReader(pdf_file)
                        text_parts = []
                        pdf_metadata["page_count"] = len(pdf_reader.pages)

                        # Extract text from each page
                        for page_num in range(len(pdf_reader.pages)):
                            page = pdf_reader.pages[page_num]
                            text_parts.append(page.extract_text() or "")

                    extracted_text = "\n".join(text_parts)
                    pdf_metadata["text_length"] = len(extracted_text)
                    pdf_metadata["text_empty"] = not extracted_text.strip()

                    return {
                        "success": True,
                        "message": "Successfully extracted text from PDF in DICOM",
                        "text_content": extracted_text,
                        "file_path": dicom_file if keep_files else "",
                        "pdf_metadata": pdf_metadata,
                    }
                else:
                    message = "Retrieved DICOM instance does not contain an encapsulated PDF"
                    success = False

            return {
                "success": success,
                "message": message,
                "text_content": extracted_text,
                "file_path": received_files[0] if (received_files and keep_files) else "",
                "pdf_metadata": pdf_metadata,
            }
