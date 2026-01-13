"""
Base DICOM client implementation.
"""

import errno
import inspect
import logging
import socket
import time
from typing import Any, Callable, List, Optional

from pynetdicom import AE, build_role
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelGet,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
    Verification,
    EncapsulatedPDFStorage,
)

# Compatibility shim for storage presentation contexts across pynetdicom versions
try:
    from pynetdicom.sop_class import AllStoragePresentationContexts as _ALL_STORAGE_CONTEXTS  # type: ignore
except Exception:
    try:
        from pynetdicom.sop_class import StoragePresentationContexts as _ALL_STORAGE_CONTEXTS  # type: ignore
    except Exception:
        _ALL_STORAGE_CONTEXTS = None  # Will fall back to scanning SOP classes

from .config import NetworkConfig
from .errors import (
    DicomAssociationError,
    DicomConfigurationError,
    DicomOperationError,
)

logger = logging.getLogger("dicom_mcp.dicom_client")
_TRANSIENT_ERRNOS = {
    errno.ETIMEDOUT,
    errno.ECONNRESET,
    errno.ECONNABORTED,
    errno.EPIPE,
}


class DicomClientBase:
    """DICOM networking client base with shared connection helpers."""

    def __init__(
        self,
        host: str,
        port: int,
        calling_aet: str,
        called_aet: str,
        query_retrieve_root: str = "study",
        network: Optional[NetworkConfig] = None,
        node_name: Optional[str] = None,
    ):
        """Initialize DICOM client.

        Args:
            host: DICOM node hostname or IP
            port: DICOM node port
            calling_aet: Local AE title (our AE title)
            called_aet: Remote AE title (the node we're connecting to)
            query_retrieve_root: Query/Retrieve root (study or patient)
            network: Network configuration for timeouts and PDU sizing
            node_name: Optional configured node name for logging
        """
        self.host = host
        self.port = port
        self.called_aet = called_aet
        self.calling_aet = calling_aet
        self.node_name = node_name
        self.query_retrieve_root = self._normalize_query_retrieve_root(query_retrieve_root)
        self.network = network or NetworkConfig()

        # Create the Application Entity
        self.ae = AE(ae_title=calling_aet)
        self._apply_network_config(self.network)

        # Add the necessary presentation contexts
        self.ae.add_requested_context(Verification)
        self._configure_query_retrieve_contexts()

        # Add storage presentation contexts and enable SCP role negotiation.
        self._configure_storage_contexts()

    @staticmethod
    def _normalize_query_retrieve_root(value: str) -> str:
        normalized = str(value).strip().lower()
        normalized = normalized.replace("-", "").replace("_", "").replace(" ", "")
        if normalized in {"study", "studyroot"}:
            return "study"
        if normalized in {"patient", "patientroot"}:
            return "patient"
        raise DicomConfigurationError("query_retrieve_root must be 'study' or 'patient'")

    def _configure_query_retrieve_contexts(self) -> None:
        if self.query_retrieve_root == "patient":
            self._find_model = PatientRootQueryRetrieveInformationModelFind
            self._get_model = PatientRootQueryRetrieveInformationModelGet
            self._move_model = PatientRootQueryRetrieveInformationModelMove
        else:
            self._find_model = StudyRootQueryRetrieveInformationModelFind
            self._get_model = StudyRootQueryRetrieveInformationModelGet
            self._move_model = StudyRootQueryRetrieveInformationModelMove

        self.ae.add_requested_context(self._find_model)
        self.ae.add_requested_context(self._get_model)
        self.ae.add_requested_context(self._move_model)
        if self.query_retrieve_root != "patient":
            # Patient-level C-FIND requires Patient Root even when Study Root is selected.
            self.ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)

    def _configure_storage_contexts(self) -> None:
        # Include storage SOP classes for C-GET/C-STORE operations.
        self.storage_roles = []
        added_storage_uids = set()

        def _add_storage_uid(uid_val):
            if uid_val in added_storage_uids:
                return
            added_storage_uids.add(uid_val)
            self.ae.add_requested_context(uid_val)
            self.storage_roles.append(build_role(uid_val, scp_role=True))

        mode = self.network.storage_contexts
        if mode == "core":
            try:
                import pynetdicom.sop_class as sc
                core_names = [
                    "CTImageStorage",
                    "MRImageStorage",
                    "UltrasoundImageStorage",
                    "UltrasoundMultiFrameImageStorage",
                    "CRImageStorage",
                    "SecondaryCaptureImageStorage",
                    "EncapsulatedPDFStorage",
                ]
                for name in core_names:
                    uid_val = getattr(sc, name, None)
                    if uid_val is not None:
                        _add_storage_uid(uid_val)
            except Exception:
                _add_storage_uid(EncapsulatedPDFStorage)
        else:
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

        logger.info(
            "Configured %s storage presentation contexts (mode=%s)",
            len(added_storage_uids),
            mode,
        )

    def _apply_network_config(self, network: NetworkConfig) -> None:
        self._set_ae_attribute(["acse_timeout"], network.acse_timeout)
        self._set_ae_attribute(["dimse_timeout"], network.dimse_timeout)
        self._set_ae_attribute(["network_timeout"], network.network_timeout)
        self._set_ae_attribute(
            ["association_timeout", "assoc_timeout", "connection_timeout"],
            network.assoc_timeout,
        )
        self._set_ae_attribute(
            ["maximum_pdu_size", "maximum_pdu_length", "max_pdu_size", "max_pdu_length"],
            network.max_pdu,
        )

    def _is_transient_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return True
        if isinstance(exc, DicomAssociationError):
            return True
        if isinstance(exc, ConnectionError):
            return True
        if isinstance(exc, OSError) and exc.errno in _TRANSIENT_ERRNOS:
            return True
        return False

    def _calculate_backoff(self, attempt: int) -> float:
        retry = self.network.retry
        delay = retry.backoff_seconds * (retry.backoff_multiplier ** (attempt - 1))
        if retry.backoff_max_seconds > 0:
            delay = min(delay, retry.backoff_max_seconds)
        return max(0.0, delay)

    def _with_retry(self, op_name: str, operation: Callable[[], Any]) -> Any:
        retry = self.network.retry
        max_attempts = max(1, retry.max_attempts)
        for attempt in range(1, max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                if attempt >= max_attempts or not self._is_transient_error(exc):
                    raise
                delay = self._calculate_backoff(attempt)
                logger.exception(
                    self._format_log_event(
                        op_name,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        retry_delay_seconds=f"{delay:.1f}",
                        error=str(exc),
                    )
                )
                if delay > 0:
                    time.sleep(delay)
        raise DicomOperationError(f"{op_name} failed after {max_attempts} attempts")

    def _get_next_message_id(self, assoc) -> Optional[int]:
        for attr_name in ("next_message_id", "next_msg_id"):
            attr = getattr(assoc, attr_name, None)
            if callable(attr):
                try:
                    return int(attr())
                except Exception:
                    continue
            if isinstance(attr, int):
                return attr
        return None

    def _send_c_find(self, assoc, query_dataset, query_model, msg_id: Optional[int]):
        if msg_id is None:
            return assoc.send_c_find(query_dataset, query_model), None
        try:
            sig = inspect.signature(assoc.send_c_find)
        except (TypeError, ValueError):
            return assoc.send_c_find(query_dataset, query_model), None
        if "msg_id" in sig.parameters:
            return assoc.send_c_find(query_dataset, query_model, msg_id=msg_id), msg_id
        if "message_id" in sig.parameters:
            return assoc.send_c_find(query_dataset, query_model, message_id=msg_id), msg_id
        return assoc.send_c_find(query_dataset, query_model), None

    def _send_c_cancel(self, assoc, msg_id: Optional[int]) -> bool:
        if msg_id is None:
            return False
        cancel = getattr(assoc, "send_c_cancel", None)
        if not callable(cancel):
            return False
        try:
            cancel(msg_id)
            return True
        except Exception as exc:
            logger.debug("Failed to send C-CANCEL for msg_id %s: %s", msg_id, exc)
            return False

    @staticmethod
    def _status_category(status_code: int) -> str:
        if status_code in (0xFF00, 0xFF01):
            return "pending"
        if status_code == 0x0000:
            return "success"
        if status_code == 0xFE00:
            return "cancel"
        if status_code == 0x0001 or 0xB000 <= status_code <= 0xBFFF:
            return "warning"
        return "failure"

    def _status_message(self, status: Any, status_code: int, category: str) -> str:
        error_comment = getattr(status, "ErrorComment", None)
        if error_comment:
            return str(error_comment)
        if category == "cancel":
            return "C-FIND canceled"
        if category == "warning":
            return f"DICOM warning status 0x{status_code:04X}"
        if category == "failure":
            return f"DICOM failure status 0x{status_code:04X}"
        return f"DICOM status 0x{status_code:04X}"

    def _set_ae_attribute(self, attr_names: List[str], value: Optional[int]) -> None:
        if value is None:
            return
        for attr_name in attr_names:
            if hasattr(self.ae, attr_name):
                setattr(self.ae, attr_name, value)
                return

    def _log_association_contexts(self, assoc, op_name: str) -> None:
        accepted = getattr(assoc, "accepted_contexts", None)
        if accepted is None:
            return
        try:
            accepted_count = len(accepted)
        except Exception:
            return
        self._log_event(
            logging.INFO,
            "association_established",
            dicom_operation=op_name,
            accepted_contexts=accepted_count,
        )

    def _format_log_event(self, operation: str, **fields: Any) -> str:
        base = {
            "operation": operation,
            "node": self.node_name,
            "called_aet": self.called_aet,
            "calling_aet": self.calling_aet,
            "host": self.host,
            "port": self.port,
        }
        for key, value in fields.items():
            if value not in (None, "", [], {}):
                base[key] = value

        ordered_keys = ("operation", "node", "called_aet", "calling_aet", "host", "port")
        parts: List[str] = []
        for key in ordered_keys:
            value = base.get(key)
            if value not in (None, "", [], {}):
                parts.append(f"{key}={value}")
        extra_keys = [key for key in base.keys() if key not in ordered_keys]
        for key in sorted(extra_keys):
            value = base[key]
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (list, tuple, set)):
                value = ",".join(str(item) for item in value)
            parts.append(f"{key}={value}")

        return "dicom_event " + " ".join(parts)

    def _log_event(self, level: int, operation: str, **fields: Any) -> None:
        logger.log(level, self._format_log_event(operation, **fields))

    def verify_connection(self) -> tuple[bool, str]:
        """Verify connectivity to the DICOM node using C-ECHO."""
        self._log_event(logging.INFO, "verify_connection")

        def _attempt() -> tuple[bool, str]:
            assoc = self.ae.associate(self.host, self.port, ae_title=self.called_aet)
            if not assoc.is_established:
                raise DicomAssociationError(
                    f"Failed to associate with DICOM node at {self.host}:{self.port} "
                    f"(Called AE: {self.called_aet}, Calling AE: {self.calling_aet})"
                )
            self._log_association_contexts(assoc, "C-ECHO")
            try:
                status = assoc.send_c_echo()
            finally:
                assoc.release()

            if status and status.Status == 0:
                return (
                    True,
                    (
                        f"Connection successful to {self.host}:{self.port} "
                        f"(Called AE: {self.called_aet}, Calling AE: {self.calling_aet})"
                    ),
                )
            return False, f"C-ECHO failed with status: {status.Status if status else 'None'}"

        try:
            return self._with_retry("C-ECHO", _attempt)
        except Exception as exc:
            logger.exception(self._format_log_event("verify_connection", error=str(exc)))
            return (
                False,
                (
                    f"Connection verification failed to {self.host}:{self.port} "
                    f"(Called AE: {self.called_aet}, Calling AE: {self.calling_aet}): {exc}"
                ),
            )
