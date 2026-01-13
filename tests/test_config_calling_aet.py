import pytest
from pydantic import ValidationError

from dicom_mcp.config import DicomConfiguration


def _base_config(**overrides):
    data = {
        "nodes": {
            "node1": {
                "host": "localhost",
                "port": 11112,
                "ae_title": "NODE",
            }
        },
        "current_node": "node1",
        "calling_aet": "LOCAL",
    }
    data.update(overrides)
    return DicomConfiguration(**data)


def test_calling_aet_title_defaults_without_calling_aets() -> None:
    config = _base_config(calling_aet="LOCAL")
    assert config.calling_aet_title == "LOCAL"


def test_calling_aet_title_resolves_by_name() -> None:
    config = _base_config(
        calling_aet="primary",
        calling_aets={
            "primary": {
                "ae_title": "MCPSCU",
                "description": "Primary caller",
            }
        },
    )
    assert config.calling_aet_title == "MCPSCU"


def test_calling_aet_title_resolves_by_alias() -> None:
    config = _base_config(
        calling_aet="alias1",
        calling_aets={
            "primary": {
                "ae_title": "MCPSCU",
                "aliases": ["alias1"],
            }
        },
    )
    assert config.calling_aet_title == "MCPSCU"


def test_calling_aet_title_resolves_by_ae_title() -> None:
    config = _base_config(
        calling_aet="MCPSCU",
        calling_aets={
            "primary": {
                "ae_title": "MCPSCU",
                "aliases": ["alias1"],
            }
        },
    )
    assert config.calling_aet_title == "MCPSCU"


def test_resolve_calling_aet_unknown_raises() -> None:
    config = _base_config(
        calling_aet="primary",
        calling_aets={
            "primary": {
                "ae_title": "MCPSCU",
            }
        },
    )

    with pytest.raises(ValueError):
        config.resolve_calling_aet("missing")


def test_calling_aet_validation_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        _base_config(
            calling_aet="missing",
            calling_aets={
                "primary": {
                    "ae_title": "MCPSCU",
                }
            },
        )
