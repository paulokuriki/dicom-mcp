"""
DICOM Client.

This module provides a clean interface to pynetdicom functionality,
abstracting the details of DICOM networking.
"""
import os
import time
import tempfile
from typing import Dict, List, Any, Tuple, Optional

from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pynetdicom import AE, evt, build_role
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelGet,
    PatientRootQueryRetrieveInformationModelMove,  # For C-MOVE
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,    # For C-MOVE
    Verification,
    EncapsulatedPDFStorage
)

# Compatibility shim for storage presentation contexts across pynetdicom versions
try:
    from pynetdicom.sop_class import AllStoragePresentationContexts as _ALL_STORAGE_CONTEXTS  # type: ignore
except Exception:
    try:
        from pynetdicom.sop_class import StoragePresentationContexts as _ALL_STORAGE_CONTEXTS  # type: ignore
    except Exception:
        _ALL_STORAGE_CONTEXTS = None  # Will fall back to scanning SOP classes

from .attributes import get_attributes_for_level

class DicomClient:
    """DICOM networking client that handles communication with DICOM nodes."""
    
    def __init__(self, host: str, port: int, calling_aet: str, called_aet: str):
        """Initialize DICOM client.
        
        Args:
            host: DICOM node hostname or IP
            port: DICOM node port
            calling_aet: Local AE title (our AE title)
            called_aet: Remote AE title (the node we're connecting to)
        """
        self.host = host
        self.port = port
        self.called_aet = called_aet
        self.calling_aet = calling_aet
        
        # Create the Application Entity
        self.ae = AE(ae_title=calling_aet)
        
        # Add the necessary presentation contexts
        self.ae.add_requested_context(Verification)
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelGet)
        self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        
        # Add storage presentation contexts and enable SCP role negotiation
        # Include as many storage SOP classes as available in this pynetdicom version
        self.storage_roles = []
        added_storage_uids = set()

        def _add_storage_uid(uid_val):
            if uid_val in added_storage_uids:
                return
            added_storage_uids.add(uid_val)
            self.ae.add_requested_context(uid_val)
            self.storage_roles.append(build_role(uid_val, scp_role=True))

        if _ALL_STORAGE_CONTEXTS is not None:
            for ctx in _ALL_STORAGE_CONTEXTS:
                abstract_syntax = getattr(ctx, "abstract_syntax", ctx)
                _add_storage_uid(abstract_syntax)
        else:
            try:
                # Fallback: scan sop_class module for all *Storage UIDs
                from pydicom.uid import UID
                import pynetdicom.sop_class as sc
                for name in dir(sc):
                    if not name.endswith("Storage"):
                        continue
                    try:
                        val = getattr(sc, name)
                    except Exception:
                        continue
                    if isinstance(val, UID):
                        _add_storage_uid(val)
            except Exception:
                # As a last resort, at least include EncapsulatedPDFStorage
                _add_storage_uid(EncapsulatedPDFStorage)
    
    def verify_connection(self) -> Tuple[bool, str]:
        """Verify connectivity to the DICOM node using C-ECHO.
        
        Returns:
            Tuple of (success, message)
        """
        # Associate with the DICOM node
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)
        
        if assoc.is_established:
            # Send C-ECHO request
            status = assoc.send_c_echo()
            
            # Release the association
            assoc.release()
            
            if status and status.Status == 0:
                return True, f"Connection successful to {self.host}:{self.port} (Called AE: {self.called_aet}, Calling AE: {self.calling_aet})"
            else:
                return False, f"C-ECHO failed with status: {status.Status if status else 'None'}"
        else:
            return False, f"Failed to associate with DICOM node at {self.host}:{self.port} (Called AE: {self.called_aet}, Calling AE: {self.calling_aet})"
    
    def find(self, query_dataset: Dataset, query_model) -> List[Dict[str, Any]]:
        """Execute a C-FIND request.
        
        Args:
            query_dataset: Dataset containing query parameters
            query_model: DICOM query model (Patient/StudyRoot)
        
        Returns:
            List of dictionaries containing query results
        
        Raises:
            Exception: If association fails
        """
        # Associate with the DICOM node
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)
        
        if not assoc.is_established:
            raise Exception(f"Failed to associate with DICOM node at {self.host}:{self.port} (Called AE: {self.called_aet}, Calling AE: {self.calling_aet})")
        
        results = []
        
        try:
            # Send C-FIND request
            responses = assoc.send_c_find(query_dataset, query_model)
            
            for (status, dataset) in responses:
                if status and status.Status == 0xFF00:  # Pending
                    if dataset:
                        results.append(self._dataset_to_dict(dataset))
        finally:
            # Always release the association
            assoc.release()
        
        return results
    
    def query_patient(self, patient_id: str = None, name_pattern: str = None, 
                     birth_date: str = None, attribute_preset: str = "standard",
                     additional_attrs: List[str] = None, exclude_attrs: List[str] = None) -> List[Dict[str, Any]]:
        """Query for patients matching criteria.
        
        Args:
            patient_id: Patient ID
            name_pattern: Patient name pattern (can include wildcards * and ?)
            birth_date: Patient birth date (YYYYMMDD)
            attribute_preset: Attribute preset (minimal, standard, extended)
            additional_attrs: Additional attributes to include
            exclude_attrs: Attributes to exclude
            
        Returns:
            List of matching patient records
        """
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
            if not hasattr(ds, attr):
                setattr(ds, attr, "")
        
        # Execute query
        return self.find(ds, PatientRootQueryRetrieveInformationModelFind)
    
    def query_study(self, patient_id: str = None, study_date: str = None, 
                   modality: str = None, study_description: str = None, 
                   accession_number: str = None, study_instance_uid: str = None,
                   attribute_preset: str = "standard", additional_attrs: List[str] = None, 
                   exclude_attrs: List[str] = None) -> List[Dict[str, Any]]:
        """Query for studies matching criteria.
        
        Args:
            patient_id: Patient ID
            study_date: Study date or range (YYYYMMDD or YYYYMMDD-YYYYMMDD)
            modality: Modalities in study
            study_description: Study description (can include wildcards)
            accession_number: Accession number
            study_instance_uid: Study Instance UID
            attribute_preset: Attribute preset (minimal, standard, extended)
            additional_attrs: Additional attributes to include
            exclude_attrs: Attributes to exclude
            
        Returns:
            List of matching study records
        """
        # Create query dataset
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        
        # Add query parameters if provided
        if patient_id:
            ds.PatientID = patient_id
            
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
            if not hasattr(ds, attr):
                setattr(ds, attr, "")
        
        # Execute query
        return self.find(ds, StudyRootQueryRetrieveInformationModelFind)
    
    def query_series(self, study_instance_uid: str, series_instance_uid: str = None,
                    modality: str = None, series_number: str = None, 
                    series_description: str = None, attribute_preset: str = "standard",
                    additional_attrs: List[str] = None, exclude_attrs: List[str] = None) -> List[Dict[str, Any]]:
        """Query for series matching criteria.
        
        Args:
            study_instance_uid: Study Instance UID (required)
            series_instance_uid: Series Instance UID
            modality: Modality (e.g. "CT", "MR")
            series_number: Series number
            series_description: Series description (can include wildcards)
            attribute_preset: Attribute preset (minimal, standard, extended)
            additional_attrs: Additional attributes to include
            exclude_attrs: Attributes to exclude
            
        Returns:
            List of matching series records
        """
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
            if not hasattr(ds, attr):
                setattr(ds, attr, "")
        
        # Execute query
        return self.find(ds, StudyRootQueryRetrieveInformationModelFind)
    
    def query_instance(self, series_instance_uid: str, sop_instance_uid: str = None,
                      instance_number: str = None, attribute_preset: str = "standard",
                      additional_attrs: List[str] = None, exclude_attrs: List[str] = None) -> List[Dict[str, Any]]:
        """Query for instances matching criteria.
        
        Args:
            series_instance_uid: Series Instance UID (required)
            sop_instance_uid: SOP Instance UID
            instance_number: Instance number
            attribute_preset: Attribute preset (minimal, standard, extended)
            additional_attrs: Additional attributes to include
            exclude_attrs: Attributes to exclude
            
        Returns:
            List of matching instance records
        """
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
            if not hasattr(ds, attr):
                setattr(ds, attr, "")
        
        # Execute query
        return self.find(ds, StudyRootQueryRetrieveInformationModelFind)
    
    def move_series(
            self, 
            destination_ae: str,
            series_instance_uid: str
        ) -> dict:
        """Move a DICOM series to another DICOM node using C-MOVE.
        
        This method performs a simple C-MOVE operation to transfer a specific series
        to a destination DICOM node.
        
        Args:
            destination_ae: AE title of the destination DICOM node
            series_instance_uid: Series Instance UID to be moved
            
        Returns:
            Dictionary with operation status:
            {
                "success": bool,
                "message": str,
                "completed": int,  # Number of successful transfers
                "failed": int,     # Number of failed transfers
                "warning": int     # Number of warnings
            }
        """
        # Create query dataset for series level
        ds = Dataset()
        ds.QueryRetrieveLevel = "SERIES"
        ds.SeriesInstanceUID = series_instance_uid
        
        # Associate with the DICOM node
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)
        
        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                "completed": 0,
                "failed": 0,
                "warning": 0
            }
        
        result = {
            "success": False,
            "message": "C-MOVE operation failed",
            "completed": 0,
            "failed": 0,
            "warning": 0
        }
        
        try:
            # Send C-MOVE request with the destination AE title
            responses = assoc.send_c_move(
                ds, 
                destination_ae, 
                PatientRootQueryRetrieveInformationModelMove
            )
            
            # Process the responses
            for (status, dataset) in responses:
                if status:
                    # Record the sub-operation counts if available
                    if hasattr(status, 'NumberOfCompletedSuboperations'):
                        result["completed"] = status.NumberOfCompletedSuboperations
                    if hasattr(status, 'NumberOfFailedSuboperations'):
                        result["failed"] = status.NumberOfFailedSuboperations
                    if hasattr(status, 'NumberOfWarningSuboperations'):
                        result["warning"] = status.NumberOfWarningSuboperations
                    
                    # Check the status code
                    if status.Status == 0x0000:  # Success
                        result["success"] = True
                        result["message"] = "C-MOVE operation completed successfully"
                    elif status.Status == 0x0001 or status.Status == 0xB000:  # Success with warnings
                        result["success"] = True
                        result["message"] = "C-MOVE operation completed with warnings or failures"
                    elif status.Status == 0xA801:  # Refused: Move destination unknown
                        result["message"] = f"C-MOVE refused: Destination '{destination_ae}' unknown"
                    else:
                        result["message"] = f"C-MOVE failed with status 0x{status.Status:04X}"
                        
                    # If we got a dataset with an error comment, add it
                    if dataset and hasattr(dataset, 'ErrorComment'):
                        result["message"] += f": {dataset.ErrorComment}"
        
        finally:
            # Always release the association
            assoc.release()
        
        return result

    def move_study(
            self, 
            destination_ae: str,
            study_instance_uid: str
        ) -> dict:
        """Move a DICOM study to another DICOM node using C-MOVE.
        
        This method performs a simple C-MOVE operation to transfer a specific study
        to a destination DICOM node.
        
        Args:
            destination_ae: AE title of the destination DICOM node
            study_instance_uid: Study Instance UID to be moved
            
        Returns:
            Dictionary with operation status:
            {
                "success": bool,
                "message": str,
                "completed": int,  # Number of successful transfers
                "failed": int,     # Number of failed transfers
                "warning": int     # Number of warnings
            }
        """
        # Create query dataset for study level
        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_instance_uid
        
        # Associate with the DICOM node
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)
        
        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                "completed": 0,
                "failed": 0,
                "warning": 0
            }
        
        result = {
            "success": False,
            "message": "C-MOVE operation failed",
            "completed": 0,
            "failed": 0,
            "warning": 0
        }
        
        try:
            # Send C-MOVE request with the destination AE title
            responses = assoc.send_c_move(
                ds, 
                destination_ae, 
                PatientRootQueryRetrieveInformationModelMove
            )
            
            # Process the responses
            for (status, dataset) in responses:
                if status:
                    # Record the sub-operation counts if available
                    if hasattr(status, 'NumberOfCompletedSuboperations'):
                        result["completed"] = status.NumberOfCompletedSuboperations
                    if hasattr(status, 'NumberOfFailedSuboperations'):
                        result["failed"] = status.NumberOfFailedSuboperations
                    if hasattr(status, 'NumberOfWarningSuboperations'):
                        result["warning"] = status.NumberOfWarningSuboperations
                    
                    # Check the status code
                    if status.Status == 0x0000:  # Success
                        result["success"] = True
                        result["message"] = "C-MOVE operation completed successfully"
                    elif status.Status == 0x0001 or status.Status == 0xB000:  # Success with warnings
                        result["success"] = True
                        result["message"] = "C-MOVE operation completed with warnings or failures"
                    elif status.Status == 0xA801:  # Refused: Move destination unknown
                        result["message"] = f"C-MOVE refused: Destination '{destination_ae}' unknown"
                    else:
                        result["message"] = f"C-MOVE failed with status 0x{status.Status:04X}"
                        
                    # If we got a dataset with an error comment, add it
                    if dataset and hasattr(dataset, 'ErrorComment'):
                        result["message"] += f": {dataset.ErrorComment}"
        
        finally:
            # Always release the association
            assoc.release()
        
        return result
    def extract_pdf_text_from_dicom(
            self, 
            study_instance_uid: str,
            series_instance_uid: str,
            sop_instance_uid: str
        ) -> Dict[str, Any]:
        """Retrieve a DICOM instance with encapsulated PDF and extract its text content.
        
        This function retrieves a DICOM instance that contains an encapsulated PDF document
        using C-GET and extracts the PDF content using PyPDF2 to parse the text content.
        
        Args:
            study_instance_uid: Study Instance UID
            series_instance_uid: Series Instance UID
            sop_instance_uid: SOP Instance UID
            
        Returns:
            Dictionary with extracted text information and status:
            {
                "success": bool,
                "message": str,
                "text_content": str,
                "file_path": str  # Path to the temporary DICOM file
            }
        """
        # Create temporary directory for storing retrieved files
        temp_dir = tempfile.mkdtemp()
        
        # Create dataset for C-GET query
        ds = Dataset()
        ds.QueryRetrieveLevel = "IMAGE"
        ds.StudyInstanceUID = study_instance_uid
        ds.SeriesInstanceUID = series_instance_uid
        ds.SOPInstanceUID = sop_instance_uid
        
        # Define a handler for C-STORE operations during C-GET
        received_files = []
        
        def handle_store(event):
            """Handle C-STORE operations during C-GET"""
            ds = event.dataset
            sop_instance = ds.SOPInstanceUID if hasattr(ds, 'SOPInstanceUID') else "unknown"
            
            # Ensure we have file meta information
            if not hasattr(ds, 'file_meta') or not hasattr(ds.file_meta, 'TransferSyntaxUID'):
                from pydicom.dataset import FileMetaDataset
                if not hasattr(ds, 'file_meta'):
                    ds.file_meta = FileMetaDataset()
                
                if event.context.transfer_syntax:
                    ds.file_meta.TransferSyntaxUID = event.context.transfer_syntax
                else:
                    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"
                
                if not hasattr(ds.file_meta, 'MediaStorageSOPClassUID') and hasattr(ds, 'SOPClassUID'):
                    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
                
                if not hasattr(ds.file_meta, 'MediaStorageSOPInstanceUID') and hasattr(ds, 'SOPInstanceUID'):
                    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
            
            # Save the dataset to file
            file_path = os.path.join(temp_dir, f"{sop_instance}.dcm")
            ds.save_as(file_path, write_like_original=False)
            received_files.append(file_path)
            
            return 0x0000  # Success
        
        # Define event handlers - using the proper format for pynetdicom
        handlers = [(evt.EVT_C_STORE, handle_store)]
        
        # Create an SCP/SCU Role Selection Negotiation item for PDF Storage
        # This is needed to indicate our AE can act as an SCP (receiver) for C-STORE operations
        # during the C-GET operation
        role = build_role(EncapsulatedPDFStorage, scp_role=True)
        
        # Associate with the DICOM node, providing the event handlers during association
        # This is the correct way to handle events in pynetdicom
        assoc = self.ae.associate(
            self.host, 
            self.port, 
            ae_title=self.called_aet,
            evt_handlers=handlers,
            ext_neg=[role]  # Add extended negotiation for SCP/SCU role selection
        )
        
        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                "text_content": "",
                "file_path": ""
            }
        
        success = False
        message = "C-GET operation failed"
        pdf_path = ""
        extracted_text = ""
        
        try:
            # Send C-GET request - without evt_handlers parameter since we provided them during association
            responses = assoc.send_c_get(ds, PatientRootQueryRetrieveInformationModelGet)
            
            for (status, dataset) in responses:
                if status:
                    status_int = status.Status if hasattr(status, 'Status') else 0
                    
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
            ds = dcmread(dicom_file)
            
            # Check if it's an encapsulated PDF
            if (hasattr(ds, 'SOPClassUID') and 
                ds.SOPClassUID == '1.2.840.10008.5.1.4.1.1.104.1'):  # Encapsulated PDF Storage
                
                # Extract the PDF data
                pdf_data = ds.EncapsulatedDocument
                
                # Write to a temporary file
                pdf_path = os.path.join(temp_dir, "extracted.pdf")
                with open(pdf_path, 'wb') as pdf_file:
                    pdf_file.write(pdf_data)
                
                import PyPDF2
                
                # Extract text from the PDF
                with open(pdf_path, 'rb') as pdf_file:
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    text_parts = []
                    
                    # Extract text from each page
                    for page_num in range(len(pdf_reader.pages)):
                        page = pdf_reader.pages[page_num]
                        text_parts.append(page.extract_text())
                    
                    extracted_text = "\n".join(text_parts)
                
                return {
                    "success": True,
                    "message": "Successfully extracted text from PDF in DICOM",
                    "text_content": extracted_text,
                    "file_path": dicom_file
                }
            else:
                message = "Retrieved DICOM instance does not contain an encapsulated PDF"
                success = False
        
        return {
            "success": success,
            "message": message,
            "text_content": extracted_text,
            "file_path": received_files[0] if received_files else ""
        }
    
    @staticmethod
    def _prepare_directory(path: str) -> str:
        """Expand, resolve, and ensure the destination directory exists."""
        resolved = os.path.abspath(os.path.expanduser(path))
        os.makedirs(resolved, exist_ok=True)
        return resolved

    def _retrieve_via_c_get(self, query_dataset: Dataset, destination_path: str) -> Dict[str, Any]:
        """Perform a C-GET and store all returned instances in destination_path."""
        destination = self._prepare_directory(destination_path)
        received_files: List[str] = []

        def handle_store(event):
            ds = event.dataset
            # Ensure file meta is present for saving
            if not hasattr(ds, "file_meta") or ds.file_meta is None:
                ds.file_meta = FileMetaDataset()
            if not getattr(ds.file_meta, "TransferSyntaxUID", None) and event.context and event.context.transfer_syntax:
                ds.file_meta.TransferSyntaxUID = event.context.transfer_syntax
            if hasattr(ds, "SOPClassUID") and not getattr(ds.file_meta, "MediaStorageSOPClassUID", None):
                ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
            if hasattr(ds, "SOPInstanceUID") and not getattr(ds.file_meta, "MediaStorageSOPInstanceUID", None):
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

            if hasattr(ds, "SOPInstanceUID") and ds.SOPInstanceUID:
                file_name = ds.SOPInstanceUID
            else:
                file_name = f"instance_{int(time.time() * 1000)}_{len(received_files) + 1}"

            file_path = os.path.join(destination, f"{file_name}.dcm")
            ds.save_as(file_path, write_like_original=False)
            received_files.append(file_path)
            return 0x0000

        handlers = [(evt.EVT_C_STORE, handle_store)]
        assoc = self.ae.associate(
            self.host,
            self.port,
            ae_title=self.called_aet,
            evt_handlers=handlers,
            ext_neg=self.storage_roles
        )

        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                "files": [],
                "destination": destination,
                "statuses": []
            }

        status_codes: List[int] = []
        try:
            responses = assoc.send_c_get(query_dataset, StudyRootQueryRetrieveInformationModelGet)
            for status, _ in responses:
                if status and hasattr(status, "Status"):
                    status_codes.append(status.Status)
        finally:
            assoc.release()

        success = bool(received_files)
        status_strings = [f"0x{code:04X}" for code in status_codes]

        if success:
            message = f"Retrieved {len(received_files)} file(s) to {destination}"
        else:
            message = "C-GET operation did not return any files"
            if status_strings:
                message += f" (statuses: {status_strings})"

        return {
            "success": success,
            "message": message,
            "files": received_files,
            "destination": destination,
            "statuses": status_strings
        }

    @staticmethod
    def _summarize_download_results(items: List[Dict[str, Any]], scope: str) -> Dict[str, Any]:
        """Aggregate per-item download results into a single response."""
        if not items:
            return {
                "success": False,
                "message": f"No {scope} were processed",
                "items": [],
                "files_downloaded": 0
            }

        total_files = sum(len(item.get("files", [])) for item in items)
        failures = [item for item in items if not item.get("success")]
        success = len(failures) == 0

        if success:
            message = f"Downloaded {total_files} file(s) across {len(items)} {scope}"
        else:
            message = f"Completed with {len(failures)} failure(s); downloaded {total_files} file(s)"

        return {
            "success": success,
            "message": message,
            "items": items,
            "files_downloaded": total_files
        }

    def download_studies(self, study_instance_uids: List[str], download_root: str) -> Dict[str, Any]:
        """Download one or more studies via C-GET."""
        if not study_instance_uids:
            return {
                "success": False,
                "message": "At least one StudyInstanceUID must be provided",
                "items": [],
                "files_downloaded": 0
            }

        items = []
        for study_uid in study_instance_uids:
            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = study_uid

            destination = os.path.join(download_root, "studies", study_uid)
            result = self._retrieve_via_c_get(ds, destination)
            result["study_instance_uid"] = study_uid
            items.append(result)

        return self._summarize_download_results(items, "studies")

    def download_series(self, study_instance_uid: str, series_instance_uids: List[str], download_root: str) -> Dict[str, Any]:
        """Download one or more series from a given study via C-GET."""
        if not study_instance_uid:
            return {
                "success": False,
                "message": "StudyInstanceUID is required",
                "items": [],
                "files_downloaded": 0
            }

        if not series_instance_uids:
            return {
                "success": False,
                "message": "At least one SeriesInstanceUID must be provided",
                "items": [],
                "files_downloaded": 0
            }

        items = []
        for series_uid in series_instance_uids:
            ds = Dataset()
            ds.QueryRetrieveLevel = "SERIES"
            ds.StudyInstanceUID = study_instance_uid
            ds.SeriesInstanceUID = series_uid

            destination = os.path.join(download_root, "studies", study_instance_uid, "series", series_uid)
            result = self._retrieve_via_c_get(ds, destination)
            result["study_instance_uid"] = study_instance_uid
            result["series_instance_uid"] = series_uid
            items.append(result)

        return self._summarize_download_results(items, "series")

    def download_instances(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        download_root: str,
        sop_instance_uids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Download individual instances from a series via C-GET."""
        if not study_instance_uid or not series_instance_uid:
            return {
                "success": False,
                "message": "StudyInstanceUID and SeriesInstanceUID are required",
                "items": [],
                "files_downloaded": 0
            }

        items = []
        target_root = os.path.join(download_root, "studies", study_instance_uid, "series", series_instance_uid)

        if sop_instance_uids:
            for sop_uid in sop_instance_uids:
                ds = Dataset()
                ds.QueryRetrieveLevel = "IMAGE"
                ds.StudyInstanceUID = study_instance_uid
                ds.SeriesInstanceUID = series_instance_uid
                ds.SOPInstanceUID = sop_uid

                result = self._retrieve_via_c_get(ds, target_root)
                result["study_instance_uid"] = study_instance_uid
                result["series_instance_uid"] = series_instance_uid
                result["sop_instance_uid"] = sop_uid
                items.append(result)
        else:
            ds = Dataset()
            ds.QueryRetrieveLevel = "IMAGE"
            ds.StudyInstanceUID = study_instance_uid
            ds.SeriesInstanceUID = series_instance_uid

            result = self._retrieve_via_c_get(ds, target_root)
            result["study_instance_uid"] = study_instance_uid
            result["series_instance_uid"] = series_instance_uid
            items.append(result)

        return self._summarize_download_results(items, "instances")
    
    @staticmethod
    def _dataset_to_dict(dataset: Dataset) -> Dict[str, Any]:
        """Convert a DICOM dataset to a dictionary.
        
        Args:
            dataset: DICOM dataset
            
        Returns:
            Dictionary representation of the dataset
        """
        if hasattr(dataset, "is_empty") and dataset.is_empty():
            return {}
        
        result = {}
        for elem in dataset:
            if elem.VR == "SQ":
                # Handle sequences
                result[elem.keyword] = [DicomClient._dataset_to_dict(item) for item in elem.value]
            else:
                # Handle regular elements
                if hasattr(elem, "keyword"):
                    try:
                        if elem.VM > 1:
                            # Multiple values
                            result[elem.keyword] = list(elem.value)
                        else:
                            # Single value
                            result[elem.keyword] = elem.value
                    except Exception:
                        # Fall back to string representation
                        result[elem.keyword] = str(elem.value)
        
        return result

    def transfer_study_via_c_move(
        self,
        study_instance_uid: str,
        destination_ae_title: str,
        destination_host: str,
        destination_port: int
    ) -> Dict[str, Any]:
        """Use C-MOVE to transfer a study to another DICOM node."""
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelMove

        ds = Dataset()
        ds.QueryRetrieveLevel = "STUDY"
        ds.StudyInstanceUID = study_instance_uid

        # Associate
        assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)

        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with {self.host}:{self.port}"
            }

        try:
            responses = assoc.send_c_move(
                ds,
                move_aet=destination_ae_title,
                query_model=StudyRootQueryRetrieveInformationModelMove
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
                "statuses": status_list
            }
        finally:
            assoc.release()
