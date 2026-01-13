"""
DICOM configuration using Pydantic.
"""

import yaml
from pathlib import Path
from typing import Dict, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator

from .errors import DicomConfigurationError


class DicomNodeConfig(BaseModel):
    """Configuration for a DICOM node"""
    host: str
    port: int
    ae_title: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class CallingAETConfig(BaseModel):
    """Configuration for a calling AE title."""
    ae_title: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class StorageConfig(BaseModel):
    """Configuration for local storage and retention."""
    path: str = "./downloads"
    retention_days: int = 30
    dir_permissions: str = "0o700"  # Owner read/write/execute only
    file_permissions: str = "0o600"  # Owner read/write only


class RetryConfig(BaseModel):
    """Configuration for retry attempts and backoff."""
    max_attempts: int = 2
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 5.0

    @field_validator("max_attempts")
    @classmethod
    def validate_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("retry.max_attempts must be >= 1")
        return value

    @field_validator("backoff_seconds", "backoff_multiplier", "backoff_max_seconds")
    @classmethod
    def validate_backoff_values(cls, value: float) -> float:
        if value < 0:
            raise ValueError("retry backoff values must be >= 0")
        return value


class NetworkConfig(BaseModel):
    """Configuration for DICOM network timeouts and PDU size."""
    acse_timeout: int = 10
    dimse_timeout: int = 30
    network_timeout: int = 30
    assoc_timeout: int = 10
    max_pdu: int = 16384
    storage_contexts: str = "all"
    retry: RetryConfig = RetryConfig()

    @field_validator("storage_contexts")
    @classmethod
    def validate_storage_contexts(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"all", "core"}:
            raise ValueError("network.storage_contexts must be 'all' or 'core'")
        return normalized


class DicomConfiguration(BaseModel):
    """Complete DICOM configuration"""
    nodes: Dict[str, DicomNodeConfig]
    current_node: str
    calling_aet: str
    calling_aets: Dict[str, CallingAETConfig] = Field(default_factory=dict)
    query_retrieve_root: str = Field(
        default="study",
        description="Query/Retrieve root to use (study or patient).",
    )
    # Optional legacy field for backward compatibility
    download_directory: str | None = None
    # New storage configuration
    storage: StorageConfig = StorageConfig()
    network: NetworkConfig = NetworkConfig()

    @property
    def download_path(self) -> str:
        """Get the effective download path, preferring legacy download_directory if set."""
        if self.download_directory:
            return self.download_directory
        return self.storage.path

    def _find_calling_aet(self, name: str) -> Optional[Tuple[str, CallingAETConfig]]:
        if not name:
            return None
        if name in self.calling_aets:
            return name, self.calling_aets[name]
        for key, calling_aet in self.calling_aets.items():
            if name in calling_aet.aliases:
                return key, calling_aet
        for key, calling_aet in self.calling_aets.items():
            if calling_aet.ae_title == name:
                return key, calling_aet
        return None

    @property
    def calling_aet_title(self) -> str:
        """Resolve the configured calling AE title."""
        if not self.calling_aets:
            return self.calling_aet
        match = self._find_calling_aet(self.calling_aet)
        if match:
            return match[1].ae_title
        return self.calling_aet

    def resolve_calling_aet(self, name: str) -> Tuple[str, CallingAETConfig]:
        """Resolve a calling AE config by name, alias, or AE title."""
        if not self.calling_aets:
            raise ValueError("No calling_aets are configured")
        match = self._find_calling_aet(name)
        if match is None:
            raise ValueError(f"Calling AE '{name}' not found in configuration")
        return match

    @field_validator("query_retrieve_root")
    @classmethod
    def validate_query_retrieve_root(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        normalized = normalized.replace("-", "").replace("_", "").replace(" ", "")
        if normalized in {"study", "studyroot"}:
            return "study"
        if normalized in {"patient", "patientroot"}:
            return "patient"
        raise ValueError("query_retrieve_root must be 'study' or 'patient'")

    @model_validator(mode="after")
    def validate_calling_aet_config(self) -> "DicomConfiguration":
        if not self.nodes:
            raise ValueError("At least one DICOM node must be configured")
        if self.current_node not in self.nodes:
            raise ValueError(
                f"current_node '{self.current_node}' not found in configuration"
            )
        if self.calling_aets and self._find_calling_aet(self.calling_aet) is None:
            raise ValueError(
                "calling_aet must match a calling_aets name, alias, or ae_title"
            )
        return self


def load_config(config_path: str) -> DicomConfiguration:
    """Load DICOM configuration from YAML file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        Parsed DicomConfiguration object
        
    Raises:
        DicomConfigurationError: If the configuration file doesn't exist or is invalid
    """
    path = Path(config_path)
    if not path.exists():
        raise DicomConfigurationError(f"Configuration file {path} not found")
    
    with open(path, 'r') as f:
        data = yaml.safe_load(f)
    
    try:
        return DicomConfiguration(**data)
    except Exception as e:
        raise DicomConfigurationError(f"Invalid configuration in {path}: {str(e)}") from e
