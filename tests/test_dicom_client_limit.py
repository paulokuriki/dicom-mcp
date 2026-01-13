from __future__ import annotations

from unittest.mock import call, patch

import pytest
from pydicom.dataset import Dataset

from dicom_mcp.config import NetworkConfig, RetryConfig
from dicom_mcp.dicom_client import DicomClient


class FakeStatus:
    def __init__(self, status: int) -> None:
        self.Status = status


class FakeAssoc:
    def __init__(self, responses) -> None:
        self._responses = responses
        self.is_established = True
        self.cancelled = False
        self.cancel_msg_id = None
        self.last_msg_id = None
        self._next_msg_id = 1

    def next_msg_id(self) -> int:
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        return msg_id

    def send_c_find(self, query_dataset, query_model, msg_id=None):
        self.last_msg_id = msg_id
        return iter(self._responses)

    def send_c_cancel(self, msg_id) -> None:
        self.cancelled = True
        self.cancel_msg_id = msg_id

    def release(self) -> None:
        return None


class FakeAE:
    def __init__(self, assoc: FakeAssoc) -> None:
        self._assoc = assoc

    def associate(self, host, port, ae_title=None):
        return self._assoc


class FlakyAE:
    def __init__(self, assoc: FakeAssoc, failures: int = 1) -> None:
        self._assoc = assoc
        self._failures = failures
        self.calls = 0

    def associate(self, host, port, ae_title=None):
        self.calls += 1
        if self.calls <= self._failures:
            raise TimeoutError("simulated timeout")
        return self._assoc


def _make_dataset(patient_id: str) -> Dataset:
    ds = Dataset()
    ds.PatientID = patient_id
    return ds


def test_find_respects_limit() -> None:
    responses = [
        (FakeStatus(0xFF00), _make_dataset("1")),
        (FakeStatus(0xFF00), _make_dataset("2")),
        (FakeStatus(0xFF00), _make_dataset("3")),
        (FakeStatus(0x0000), None),
    ]
    assoc = FakeAssoc(responses)
    client = DicomClient(host="localhost", port=4242, calling_aet="TEST", called_aet="TEST")
    client.ae = FakeAE(assoc)

    result = client.find(Dataset(), None, limit=2)

    assert result["success"] is True
    assert len(result["results"]) == 2
    assert result["results"][0]["PatientID"] == "1"
    assert result["results"][1]["PatientID"] == "2"


def test_find_without_limit_returns_all() -> None:
    responses = [
        (FakeStatus(0xFF00), _make_dataset("1")),
        (FakeStatus(0xFF00), _make_dataset("2")),
        (FakeStatus(0x0000), None),
    ]
    assoc = FakeAssoc(responses)
    client = DicomClient(host="localhost", port=4242, calling_aet="TEST", called_aet="TEST")
    client.ae = FakeAE(assoc)

    result = client.find(Dataset(), None)

    assert result["success"] is True
    assert len(result["results"]) == 2


def test_find_sends_cancel_on_limit() -> None:
    responses = [
        (FakeStatus(0xFF00), _make_dataset("1")),
        (FakeStatus(0xFF00), _make_dataset("2")),
        (FakeStatus(0x0000), None),
    ]
    assoc = FakeAssoc(responses)
    client = DicomClient(host="localhost", port=4242, calling_aet="TEST", called_aet="TEST")
    client.ae = FakeAE(assoc)

    result = client.find(Dataset(), None, limit=1)

    assert result["success"] is True
    assert len(result["results"]) == 1
    assert assoc.cancelled is True
    assert assoc.cancel_msg_id == assoc.last_msg_id


def test_find_retries_on_transient_errors() -> None:
    responses = [
        (FakeStatus(0xFF00), _make_dataset("1")),
        (FakeStatus(0x0000), None),
    ]
    assoc = FakeAssoc(responses)
    network = NetworkConfig(
        retry=RetryConfig(
            max_attempts=2,
            backoff_seconds=0,
            backoff_multiplier=1.0,
            backoff_max_seconds=0,
        )
    )
    client = DicomClient(
        host="localhost",
        port=4242,
        calling_aet="TEST",
        called_aet="TEST",
        network=network,
    )
    client.ae = FlakyAE(assoc, failures=1)

    result = client.find(Dataset(), None, limit=1)

    assert result["success"] is True
    assert len(result["results"]) == 1
    assert client.ae.calls == 2


def test_calculate_backoff_without_cap() -> None:
    network = NetworkConfig(
        retry=RetryConfig(
            max_attempts=3,
            backoff_seconds=1.0,
            backoff_multiplier=2.0,
            backoff_max_seconds=0,
        )
    )
    client = DicomClient(
        host="localhost",
        port=4242,
        calling_aet="TEST",
        called_aet="TEST",
        network=network,
    )

    assert client._calculate_backoff(1) == pytest.approx(1.0)
    assert client._calculate_backoff(2) == pytest.approx(2.0)
    assert client._calculate_backoff(3) == pytest.approx(4.0)


def test_with_retry_applies_backoff_and_caps_sleep() -> None:
    responses = [
        (FakeStatus(0xFF00), _make_dataset("1")),
        (FakeStatus(0x0000), None),
    ]
    assoc = FakeAssoc(responses)
    network = NetworkConfig(
        retry=RetryConfig(
            max_attempts=3,
            backoff_seconds=2.0,
            backoff_multiplier=3.0,
            backoff_max_seconds=4.0,
        )
    )
    client = DicomClient(
        host="localhost",
        port=4242,
        calling_aet="TEST",
        called_aet="TEST",
        network=network,
    )
    client.ae = FlakyAE(assoc, failures=2)

    with patch("dicom_mcp.dicom_client_base.time.sleep") as sleep_mock:
        result = client.find(Dataset(), None, limit=1)

    assert result["success"] is True
    assert sleep_mock.call_args_list == [call(2.0), call(4.0)]


def test_with_retry_non_transient_error_does_not_retry() -> None:
    network = NetworkConfig(
        retry=RetryConfig(
            max_attempts=3,
            backoff_seconds=1.0,
            backoff_multiplier=2.0,
            backoff_max_seconds=5.0,
        )
    )
    client = DicomClient(
        host="localhost",
        port=4242,
        calling_aet="TEST",
        called_aet="TEST",
        network=network,
    )
    calls = 0

    def _operation() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("boom")

    with patch("dicom_mcp.dicom_client_base.time.sleep") as sleep_mock:
        with pytest.raises(ValueError):
            client._with_retry("TEST", _operation)

    assert calls == 1
    sleep_mock.assert_not_called()
