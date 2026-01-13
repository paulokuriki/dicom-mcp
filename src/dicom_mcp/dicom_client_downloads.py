"""
DICOM download operations and file helpers.
"""

import inspect
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydicom.dataset import Dataset, FileMetaDataset
from pynetdicom import evt

from .errors import StorageSecurityError

logger = logging.getLogger("dicom_mcp.dicom_client")


class DicomClientDownloadMixin:
    """Download-related DICOM operations."""

    @staticmethod
    def _prepare_directory(path: str, dir_permissions: str = "") -> str:
        """Expand, resolve, and ensure the destination directory exists."""
        resolved = os.path.abspath(os.path.expanduser(path))
        os.makedirs(resolved, exist_ok=True)
        DicomClientDownloadMixin._apply_permissions(resolved, dir_permissions)
        return resolved

    @staticmethod
    def _validate_safe_path(base_dir: str, target_path: str) -> bool:
        """Ensure target_path is within base_dir to prevent path traversal."""
        base = os.path.realpath(os.path.abspath(base_dir))
        target = os.path.realpath(os.path.abspath(target_path))
        return os.path.commonpath([base, target]) == base

    @staticmethod
    def _ensure_safe_path(base_dir: str, target_path: str) -> None:
        """Validate a path and raise if it escapes the base directory."""
        if not DicomClientDownloadMixin._validate_safe_path(base_dir, target_path):
            raise StorageSecurityError(
                f"Security violation: Invalid path {target_path}",
                details={"base_dir": base_dir, "target_path": target_path},
            )

    @staticmethod
    def _sanitize_filename(value: str, max_length: int = 128) -> str:
        """Sanitize a filename segment by removing path separators and limiting length."""
        if not value:
            return "unknown"
        sanitized = str(value)
        for sep in (os.sep, os.altsep):
            if sep:
                sanitized = sanitized.replace(sep, "_")
        sanitized = sanitized.strip()
        if not sanitized:
            sanitized = "unknown"
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        return sanitized

    @staticmethod
    def _apply_permissions(path: str, mode_str: str) -> None:
        """Apply file permissions."""
        if not mode_str:
            return
        try:
            if isinstance(mode_str, int):
                mode = mode_str
            else:
                raw = str(mode_str).strip().lower()
                if not raw:
                    return
                if raw.startswith(("0o", "0x", "0b")):
                    mode = int(raw, 0)
                else:
                    mode = int(raw, 8)
            os.chmod(path, mode)
        except Exception as exc:
            logger.exception("Failed to apply permissions %s to %s: %s", mode_str, path, exc)

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _write_json_atomic(
        file_path: str,
        payload: Dict[str, Any],
        file_permissions: str = "",
    ) -> None:
        """Write JSON to file atomically to avoid partial writes."""
        tmp_path = f"{file_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as tmp_file:
                json.dump(payload, tmp_file, indent=2, sort_keys=True)
                tmp_file.write("\n")
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, file_path)
            DicomClientDownloadMixin._apply_permissions(file_path, file_permissions)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception as cleanup_exc:
                logger.exception("Failed to remove temp file %s: %s", tmp_path, cleanup_exc)
            raise

    def _build_download_manifest(
        self,
        operation: str,
        destination: str,
        query: Dict[str, Any],
        instances: List[Dict[str, Any]],
        statuses: List[str],
        source_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = {
            "host": self.host,
            "port": self.port,
            "called_ae_title": self.called_aet,
            "calling_ae_title": self.calling_aet,
        }
        if source_node:
            source["node_name"] = source_node

        return {
            "manifest_version": "1.0",
            "generated_at": self._utc_timestamp(),
            "operation": operation,
            "source": source,
            "destination": destination,
            "query": query,
            "counts": {"files": len(instances)},
            "instances": instances,
            "statuses": statuses,
        }

    def _write_download_manifest(
        self,
        destination: str,
        manifest: Dict[str, Any],
        file_permissions: str = "",
    ) -> str:
        manifest_path = os.path.join(destination, "manifest.json")
        self._write_json_atomic(manifest_path, manifest, file_permissions)
        return manifest_path

    def _record_download_manifest(
        self,
        result: Dict[str, Any],
        operation: str,
        query: Dict[str, Any],
        file_permissions: str,
        source_node: Optional[str] = None,
    ) -> None:
        destination = result.get("destination")
        if not destination:
            return
        manifest = self._build_download_manifest(
            operation=operation,
            destination=destination,
            query=query,
            instances=result.get("instances", []),
            statuses=result.get("statuses", []),
            source_node=source_node,
        )
        try:
            result["manifest_path"] = self._write_download_manifest(
                destination,
                manifest,
                file_permissions=file_permissions,
            )
        except Exception as exc:
            logger.exception("Failed to write download manifest in %s: %s", destination, exc)
            result["manifest_error"] = str(exc)

    @staticmethod
    def _save_dataset_atomic(
        dataset: Dataset,
        file_path: str,
        file_permissions: str = "",
    ) -> None:
        """Write a dataset atomically to avoid leaving partial files on failure."""
        tmp_path = f"{file_path}.tmp"
        try:
            try:
                sig = inspect.signature(dataset.save_as)
            except (TypeError, ValueError):
                sig = None
            if sig and "enforce_file_format" in sig.parameters:
                dataset.save_as(tmp_path, enforce_file_format=True)
            else:
                dataset.save_as(tmp_path, write_like_original=False)
            with open(tmp_path, "rb") as tmp_file:
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, file_path)
            DicomClientDownloadMixin._apply_permissions(file_path, file_permissions)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception as cleanup_exc:
                logger.exception("Failed to remove temp file %s: %s", tmp_path, cleanup_exc)
            raise

    def _retrieve_via_c_get(
        self,
        query_dataset: Dataset,
        destination_path: str,
        file_permissions: str = "0o600",
        dir_permissions: str = "0o700",
    ) -> Dict[str, Any]:
        """Perform a C-GET and store all returned instances in destination_path."""
        destination = self._prepare_directory(destination_path, dir_permissions)
        received_files: List[str] = []
        received_instances: List[Dict[str, Any]] = []

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
                # Prefer deterministic filenames to simplify downstream handling.
                file_name = ds.SOPInstanceUID
            else:
                file_name = f"instance_{int(time.time() * 1000)}_{len(received_files) + 1}"
            file_name = self._sanitize_filename(file_name)

            file_path = os.path.join(destination, f"{file_name}.dcm")
            # Guard against path traversal if UIDs contain unexpected separators.
            if not self._validate_safe_path(destination, file_path):
                self._log_event(logging.ERROR, "path_traversal", file_path=file_path)
                return 0xC000
            try:
                self._save_dataset_atomic(ds, file_path, file_permissions)
                received_files.append(file_path)
                received_instances.append(
                    {
                        "study_instance_uid": getattr(ds, "StudyInstanceUID", ""),
                        "series_instance_uid": getattr(ds, "SeriesInstanceUID", ""),
                        "sop_instance_uid": getattr(ds, "SOPInstanceUID", ""),
                        "file_path": file_path,
                        "relative_path": os.path.relpath(file_path, destination),
                        "received_at": self._utc_timestamp(),
                    }
                )
                return 0x0000
            except Exception as exc:
                logger.exception(self._format_log_event("save_instance", file_path=file_path, error=str(exc)))
                return 0xC000

        handlers = [(evt.EVT_C_STORE, handle_store)]
        assoc = self.ae.associate(
            self.host,
            self.port,
            ae_title=self.called_aet,
            evt_handlers=handlers,
            ext_neg=self.storage_roles,
        )

        if not assoc.is_established:
            return {
                "success": False,
                "message": f"Failed to associate with DICOM node at {self.host}:{self.port}",
                "files": [],
                "destination": destination,
                "statuses": [],
            }

        status_codes: List[int] = []
        try:
            self._log_association_contexts(assoc, "C-GET")
            responses = assoc.send_c_get(query_dataset, self._get_model)
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
            "instances": received_instances,
            "destination": destination,
            "statuses": status_strings,
        }

    @staticmethod
    def _summarize_download_results(items: List[Dict[str, Any]], scope: str) -> Dict[str, Any]:
        """Aggregate per-item download results into a single response."""
        if not items:
            return {
                "success": False,
                "message": f"No {scope} were processed",
                "items": [],
                "files_downloaded": 0,
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
            "files_downloaded": total_files,
        }

    def download_studies(
        self,
        study_instance_uids: List[str],
        download_root: str,
        file_permissions: str = "0o600",
        dir_permissions: str = "0o700",
        source_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download one or more studies via C-GET."""
        self._log_event(
            logging.INFO,
            "download_studies",
            study_uids_count=len(study_instance_uids or []),
        )
        if not study_instance_uids:
            return {
                "success": False,
                "message": "At least one StudyInstanceUID must be provided",
                "items": [],
                "files_downloaded": 0,
            }

        items = []
        for study_uid in study_instance_uids:
            self._log_event(
                logging.INFO,
                "download_study",
                study_instance_uid=study_uid,
            )
            ds = Dataset()
            ds.QueryRetrieveLevel = "STUDY"
            ds.StudyInstanceUID = study_uid

            destination = os.path.join(download_root, "studies", study_uid)
            try:
                self._ensure_safe_path(download_root, destination)
            except StorageSecurityError as exc:
                items.append(
                    {
                        "success": False,
                        "message": str(exc),
                        "files": [],
                        "destination": destination,
                        "study_instance_uid": study_uid,
                        "error": exc.to_dict(),
                    }
                )
                continue
            result = self._retrieve_via_c_get(
                ds,
                destination,
                file_permissions=file_permissions,
                dir_permissions=dir_permissions,
            )
            result["study_instance_uid"] = study_uid
            self._record_download_manifest(
                result,
                operation="download_studies",
                query={
                    "retrieve_level": "STUDY",
                    "study_instance_uid": study_uid,
                },
                file_permissions=file_permissions,
                source_node=source_node,
            )
            items.append(result)

        return self._summarize_download_results(items, "studies")

    def download_series(
        self,
        study_instance_uid: str,
        series_instance_uids: List[str],
        download_root: str,
        file_permissions: str = "0o600",
        dir_permissions: str = "0o700",
        source_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download one or more series from a given study via C-GET."""
        self._log_event(
            logging.INFO,
            "download_series",
            study_instance_uid=study_instance_uid,
            series_uids_count=len(series_instance_uids or []),
        )
        if not study_instance_uid:
            return {
                "success": False,
                "message": "StudyInstanceUID is required",
                "items": [],
                "files_downloaded": 0,
            }

        if not series_instance_uids:
            return {
                "success": False,
                "message": "At least one SeriesInstanceUID must be provided",
                "items": [],
                "files_downloaded": 0,
            }

        items = []
        for series_uid in series_instance_uids:
            self._log_event(
                logging.INFO,
                "download_series_item",
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_uid,
            )
            ds = Dataset()
            ds.QueryRetrieveLevel = "SERIES"
            ds.StudyInstanceUID = study_instance_uid
            ds.SeriesInstanceUID = series_uid

            destination = os.path.join(download_root, "studies", study_instance_uid, "series", series_uid)
            try:
                self._ensure_safe_path(download_root, destination)
            except StorageSecurityError as exc:
                items.append(
                    {
                        "success": False,
                        "message": str(exc),
                        "files": [],
                        "destination": destination,
                        "study_instance_uid": study_instance_uid,
                        "series_instance_uid": series_uid,
                        "error": exc.to_dict(),
                    }
                )
                continue
            result = self._retrieve_via_c_get(
                ds,
                destination,
                file_permissions=file_permissions,
                dir_permissions=dir_permissions,
            )
            result["study_instance_uid"] = study_instance_uid
            result["series_instance_uid"] = series_uid
            self._record_download_manifest(
                result,
                operation="download_series",
                query={
                    "retrieve_level": "SERIES",
                    "study_instance_uid": study_instance_uid,
                    "series_instance_uid": series_uid,
                },
                file_permissions=file_permissions,
                source_node=source_node,
            )
            items.append(result)

        return self._summarize_download_results(items, "series")

    def download_instances(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        download_root: str,
        sop_instance_uids: Optional[List[str]] = None,
        file_permissions: str = "0o600",
        dir_permissions: str = "0o700",
        source_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download individual instances from a series via C-GET."""
        self._log_event(
            logging.INFO,
            "download_instances",
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
            sop_uids_count=len(sop_instance_uids or []),
        )
        if not study_instance_uid or not series_instance_uid:
            return {
                "success": False,
                "message": "StudyInstanceUID and SeriesInstanceUID are required",
                "items": [],
                "files_downloaded": 0,
            }

        items = []
        target_root = os.path.join(download_root, "studies", study_instance_uid, "series", series_instance_uid)
        try:
            self._ensure_safe_path(download_root, target_root)
        except StorageSecurityError as exc:
            return {
                "success": False,
                "message": str(exc),
                "items": [],
                "files_downloaded": 0,
                "error": exc.to_dict(),
            }

        manifest_instances: List[Dict[str, Any]] = []
        manifest_statuses: List[str] = []

        if sop_instance_uids:
            for sop_uid in sop_instance_uids:
                self._log_event(
                    logging.INFO,
                    "download_instance",
                    study_instance_uid=study_instance_uid,
                    series_instance_uid=series_instance_uid,
                    sop_instance_uid=sop_uid,
                )
                ds = Dataset()
                ds.QueryRetrieveLevel = "IMAGE"
                ds.StudyInstanceUID = study_instance_uid
                ds.SeriesInstanceUID = series_instance_uid
                ds.SOPInstanceUID = sop_uid

                result = self._retrieve_via_c_get(
                    ds,
                    target_root,
                    file_permissions=file_permissions,
                    dir_permissions=dir_permissions,
                )
                result["study_instance_uid"] = study_instance_uid
                result["series_instance_uid"] = series_instance_uid
                result["sop_instance_uid"] = sop_uid
                manifest_instances.extend(result.get("instances", []))
                manifest_statuses.extend(result.get("statuses", []))
                items.append(result)
        else:
            self._log_event(
                logging.INFO,
                "download_instances_series",
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
            )
            ds = Dataset()
            ds.QueryRetrieveLevel = "IMAGE"
            ds.StudyInstanceUID = study_instance_uid
            ds.SeriesInstanceUID = series_instance_uid

            result = self._retrieve_via_c_get(
                ds,
                target_root,
                file_permissions=file_permissions,
                dir_permissions=dir_permissions,
            )
            result["study_instance_uid"] = study_instance_uid
            result["series_instance_uid"] = series_instance_uid
            manifest_instances = result.get("instances", [])
            manifest_statuses = result.get("statuses", [])
            items.append(result)

        summary = self._summarize_download_results(items, "instances")
        manifest_query: Dict[str, Any] = {
            "retrieve_level": "IMAGE",
            "study_instance_uid": study_instance_uid,
            "series_instance_uid": series_instance_uid,
        }
        if sop_instance_uids:
            manifest_query["sop_instance_uids"] = list(sop_instance_uids)
        manifest = self._build_download_manifest(
            operation="download_instances",
            destination=target_root,
            query=manifest_query,
            instances=manifest_instances,
            statuses=manifest_statuses,
            source_node=source_node,
        )
        try:
            summary["manifest_path"] = self._write_download_manifest(
                target_root,
                manifest,
                file_permissions=file_permissions,
            )
        except Exception as exc:
            logger.exception("Failed to write download manifest in %s: %s", target_root, exc)
            summary["manifest_error"] = str(exc)
        return summary
