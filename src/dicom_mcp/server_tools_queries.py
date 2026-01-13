"""
Query tool registrations.
"""

from typing import Any, Dict, List

from mcp.server.fastmcp import Context, FastMCP

from .errors import DicomOperationError
from .server_tools_common import ToolDependencies


def register_query_tools(mcp: FastMCP, deps: ToolDependencies) -> None:
    """Register query-related MCP tools."""

    @mcp.tool()
    def query_patients(
        name_pattern: str = "",
        patient_id: str = "",
        birth_date: str = "",
        attribute_preset: str = "standard",
        additional_attributes: List[str] = None,
        exclude_attributes: List[str] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Query patients matching the specified criteria from the DICOM node.

        This tool performs a DICOM C-FIND operation at the PATIENT level to find patients
        matching the provided search criteria. All search parameters are optional and can
        be combined for more specific queries.

        Args:
            name_pattern: Patient name pattern (can include wildcards * and ?), e.g., "SMITH*"
            patient_id: Patient ID to search for, e.g., "12345678"
            birth_date: Patient birth date in YYYYMMDD format, e.g., "19700101"
            attribute_preset: Controls which attributes to include in results:
                - "minimal": Only essential attributes
                - "standard": Common attributes (default)
                - "extended": All available attributes
            additional_attributes: List of specific DICOM attributes to include beyond the preset
            exclude_attributes: List of DICOM attributes to exclude from the results

        Returns:
            Dictionary containing:
            - success: Boolean indicating if the query completed without failure
            - results: List of matched patient records
            - dicom_statuses: List of DICOM status entries
            - warnings: List of warning entries
            - error: Optional error dictionary

        Example:
            {
                "success": true,
                "results": [
                    {
                        "PatientID": "12345",
                        "PatientName": "SMITH^JOHN",
                        "PatientBirthDate": "19700101",
                        "PatientSex": "M"
                    }
                ],
                "dicom_statuses": [{"code": "0x0000", "category": "success"}],
                "warnings": [],
                "error": null
            }

        Notes:
            Returns success False if the query fails.
        """
        dicom_ctx = ctx.request_context.lifespan_context
        client = deps.create_client(dicom_ctx.config)

        try:
            return client.query_patient(
                patient_id=patient_id,
                name_pattern=name_pattern,
                birth_date=birth_date,
                attribute_preset=attribute_preset,
                additional_attrs=additional_attributes,
                exclude_attrs=exclude_attributes,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "query_patients",
                dicom_ctx.config,
                DicomOperationError(f"Error querying patients: {str(exc)}"),
                base_payload={
                    "results": [],
                    "dicom_statuses": [],
                    "warnings": [],
                },
            )

    @mcp.tool()
    def query_studies(
        patient_id: str = "",
        patient_name: str = "",
        patient_sex: str = "",
        patient_birth_date: str = "",
        study_date: str = "",
        modality_in_study: str = "",
        study_description: str = "",
        accession_number: str = "",
        study_instance_uid: str = "",
        limit: int | None = None,
        attribute_preset: str = "standard",
        additional_attributes: List[str] = None,
        exclude_attributes: List[str] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Query studies matching the specified criteria from the DICOM node.

        This tool performs a DICOM C-FIND operation at the STUDY level to find studies
        matching the provided search criteria. All search parameters are optional and can
        be combined for more specific queries.

        Args:
            patient_id: Patient ID to search for, e.g., "12345678"
            patient_name: Patient name to search for (can include wildcards)
            patient_sex: Patient sex (F, M, O)
            patient_birth_date: Patient birth date or range in DICOM format:
                - Single date: "19700101"
                - Date range: "19700101-19801231"
            study_date: Study date or date range in DICOM format:
                - Single date: "20230101"
                - Date range: "20230101-20230131"
            modality_in_study: Filter by modalities present in study, e.g., "CT" or "MR"
            study_description: Study description text (can include wildcards), e.g., "CHEST*"
            accession_number: Medical record accession number
            study_instance_uid: Unique identifier for a specific study
            limit: Maximum number of results to return (None = no limit)
            attribute_preset: Controls which attributes to include in results:
                - "minimal": Only essential attributes
                - "standard": Common attributes (default)
                - "extended": All available attributes
            additional_attributes: List of specific DICOM attributes to include beyond the preset
            exclude_attributes: List of DICOM attributes to exclude from the results

        Returns:
            Dictionary containing query results and status metadata. The results list includes
            entries like:
            {
                "StudyInstanceUID": "1.2.840.113619.2.1.1.322.1600364094.412.1009",
                "StudyDate": "20230215",
                "StudyDescription": "CHEST CT",
                "PatientID": "12345",
                "PatientName": "SMITH^JOHN",
                "ModalitiesInStudy": "CT"
            }

        Notes:
            Returns success False if the query fails.
        """
        dicom_ctx = ctx.request_context.lifespan_context
        client = deps.create_client(dicom_ctx.config)

        try:
            return client.query_study(
                patient_id=patient_id,
                patient_name=patient_name,
                patient_sex=patient_sex,
                patient_birth_date=patient_birth_date,
                study_date=study_date,
                modality=modality_in_study,
                study_description=study_description,
                accession_number=accession_number,
                study_instance_uid=study_instance_uid,
                limit=limit,
                attribute_preset=attribute_preset,
                additional_attrs=additional_attributes,
                exclude_attrs=exclude_attributes,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "query_studies",
                dicom_ctx.config,
                DicomOperationError(f"Error querying studies: {str(exc)}"),
                base_payload={
                    "results": [],
                    "dicom_statuses": [],
                    "warnings": [],
                },
            )

    @mcp.tool()
    def query_series(
        study_instance_uid: str,
        modality: str = "",
        series_number: str = "",
        series_description: str = "",
        series_instance_uid: str = "",
        limit: int | None = None,
        attribute_preset: str = "standard",
        additional_attributes: List[str] = None,
        exclude_attributes: List[str] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Query series within a study from the DICOM node.

        This tool performs a DICOM C-FIND operation at the SERIES level to find series
        within a specified study. The study_instance_uid is required, and additional
        parameters can be used to filter the results.

        Args:
            study_instance_uid: Unique identifier for the study (required)
            modality: Filter by imaging modality, e.g., "CT", "MR", "US", "CR"
            series_number: Filter by series number
            series_description: Series description text (can include wildcards), e.g., "AXIAL*"
            series_instance_uid: Unique identifier for a specific series
            limit: Maximum number of results to return (None = no limit)
            attribute_preset: Controls which attributes to include in results:
                - "minimal": Only essential attributes
                - "standard": Common attributes (default)
                - "extended": All available attributes
            additional_attributes: List of specific DICOM attributes to include beyond the preset
            exclude_attributes: List of DICOM attributes to exclude from the results

        Returns:
            Dictionary containing query results and status metadata. The results list includes
            entries like:
            {
                "SeriesInstanceUID": "1.2.840.113619.2.1.1.322.1600364094.412.2005",
                "SeriesNumber": "2",
                "SeriesDescription": "AXIAL 2.5MM",
                "Modality": "CT",
                "NumberOfSeriesRelatedInstances": "120"
            }

        Notes:
            Returns success False if the query fails.
        """
        dicom_ctx = ctx.request_context.lifespan_context
        client = deps.create_client(dicom_ctx.config)

        try:
            return client.query_series(
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
                modality=modality,
                series_number=series_number,
                series_description=series_description,
                limit=limit,
                attribute_preset=attribute_preset,
                additional_attrs=additional_attributes,
                exclude_attrs=exclude_attributes,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "query_series",
                dicom_ctx.config,
                DicomOperationError(f"Error querying series: {str(exc)}"),
                base_payload={
                    "results": [],
                    "dicom_statuses": [],
                    "warnings": [],
                },
            )

    @mcp.tool()
    def query_instances(
        series_instance_uid: str,
        instance_number: str = "",
        sop_instance_uid: str = "",
        attribute_preset: str = "standard",
        additional_attributes: List[str] = None,
        exclude_attributes: List[str] = None,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Query individual DICOM instances (images) within a series.

        This tool performs a DICOM C-FIND operation at the IMAGE level to find individual
        DICOM instances within a specified series. The series_instance_uid is required,
        and additional parameters can be used to filter the results.

        Args:
            series_instance_uid: Unique identifier for the series (required)
            instance_number: Filter by specific instance number within the series
            sop_instance_uid: Unique identifier for a specific instance
            attribute_preset: Controls which attributes to include in results:
                - "minimal": Only essential attributes
                - "standard": Common attributes (default)
                - "extended": All available attributes
            additional_attributes: List of specific DICOM attributes to include beyond the preset
            exclude_attributes: List of DICOM attributes to exclude from the results

        Returns:
            Dictionary containing query results and status metadata. The results list includes
            entries like:
            {
                "SOPInstanceUID": "1.2.840.113619.2.1.1.322.1600364094.412.3001",
                "SOPClassUID": "1.2.840.10008.5.1.4.1.1.2",
                "InstanceNumber": "45",
                "ContentDate": "20230215",
                "ContentTime": "152245"
            }

        Notes:
            Returns success False if the query fails.
        """
        dicom_ctx = ctx.request_context.lifespan_context
        client = deps.create_client(dicom_ctx.config)

        try:
            return client.query_instance(
                series_instance_uid=series_instance_uid,
                sop_instance_uid=sop_instance_uid,
                instance_number=instance_number,
                attribute_preset=attribute_preset,
                additional_attrs=additional_attributes,
                exclude_attrs=exclude_attributes,
            )
        except Exception as exc:
            return deps.tool_error_response(
                "query_instances",
                dicom_ctx.config,
                DicomOperationError(f"Error querying instances: {str(exc)}"),
                base_payload={
                    "results": [],
                    "dicom_statuses": [],
                    "warnings": [],
                },
            )
