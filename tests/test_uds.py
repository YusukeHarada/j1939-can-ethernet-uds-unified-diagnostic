from __future__ import annotations

import pytest

from udsdiag.uds import (
    DiagnosticError,
    UdsMessage,
    format_hex_bytes,
    parse_hex_bytes,
    parse_int,
    parse_optional_int,
    uds_from_row,
    uds_to_row,
)


def test_uds_message_round_trip_with_did() -> None:
    message = UdsMessage(service_id=0x22, did=0xF190, payload=b"\x12\x34")

    decoded = UdsMessage.from_payload(message.to_payload())

    assert decoded == message
    assert uds_to_row(decoded) == {
        "service_id": "0x22",
        "did": "0xF190",
        "payload_hex": "12 34",
        "status": "request",
    }


def test_uds_message_round_trip_without_did_and_positive_status() -> None:
    message = UdsMessage(service_id=0x62, did=None, payload=b"\xf1\x90\xaa")

    decoded = UdsMessage.from_payload(message.to_payload())

    assert decoded == UdsMessage(service_id=0x62, did=0xF190, payload=b"\xaa")
    assert decoded.status() == "positive_response"


def test_negative_response_status() -> None:
    assert UdsMessage(service_id=0x7F, did=None, payload=b"\x22\x31").status() == "negative_response"


def test_validate_client_request() -> None:
    UdsMessage(service_id=0x22, did=0xF190, payload=b"").validate_client_request()
    UdsMessage(service_id=0x85, did=None, payload=b"\x02").validate_client_request()

    with pytest.raises(DiagnosticError, match="not a supported UDS client request"):
        UdsMessage(service_id=0x7F, did=None, payload=b"\x22\x31").validate_client_request()


def test_uds_from_row_accepts_missing_payload() -> None:
    row = {"service_id": "0x3E", "did": "", "payload_hex": ""}

    assert uds_from_row(row) == UdsMessage(service_id=0x3E, did=None, payload=b"")


def test_parse_helpers() -> None:
    assert parse_int("15", field="value", minimum=0, maximum=20) == 15
    assert parse_optional_int(" ", field="value", minimum=0, maximum=20) is None
    assert parse_hex_bytes("AA_BB cc") == b"\xaa\xbb\xcc"
    assert format_hex_bytes(b"") == ""


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "value is required"),
        ("oops", "value must be an integer"),
        ("21", "value out of range"),
    ],
)
def test_parse_int_errors(text: str, message: str) -> None:
    with pytest.raises(DiagnosticError, match=message):
        parse_int(text, field="value", minimum=0, maximum=20)


@pytest.mark.parametrize("payload", ["A", "GG"])
def test_parse_hex_bytes_errors(payload: str) -> None:
    with pytest.raises(DiagnosticError):
        parse_hex_bytes(payload)


def test_empty_payload_rejected() -> None:
    with pytest.raises(DiagnosticError, match="UDS payload is empty"):
        UdsMessage.from_payload(b"")
