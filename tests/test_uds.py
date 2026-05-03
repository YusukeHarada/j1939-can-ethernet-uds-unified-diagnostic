from __future__ import annotations

import pytest

from udsdiag.uds import (
    DiagnosticError,
    UdsMessage,
    build_negative_response,
    build_positive_response,
    build_server_response,
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
    message = UdsMessage(service_id=0x7F, did=None, payload=b"\x22\x31")

    assert message.status() == "negative_response"


def test_validate_client_request() -> None:
    UdsMessage(service_id=0x22, did=0xF190, payload=b"").validate_client_request()
    UdsMessage(service_id=0x85, did=None, payload=b"\x02").validate_client_request()

    with pytest.raises(DiagnosticError, match="not a supported UDS client request"):
        UdsMessage(service_id=0x7F, did=None, payload=b"\x22\x31").validate_client_request()


def test_build_positive_response() -> None:
    request = UdsMessage(service_id=0x22, did=0xF190, payload=b"")

    response = build_positive_response(request, response_payload=b"\x12\x34")

    assert response == UdsMessage(service_id=0x62, did=0xF190, payload=b"\x12\x34")
    assert response.status() == "positive_response"


def test_build_server_response_uses_negative_response_for_non_client_request() -> None:
    request = UdsMessage(service_id=0x62, did=0xF190, payload=b"\x12\x34")

    response = build_server_response(request, negative_response_code=0x12)

    assert response == UdsMessage(service_id=0x7F, did=None, payload=b"\x62\x12")


def test_build_negative_response_rejects_invalid_response_code() -> None:
    with pytest.raises(DiagnosticError, match="negative response code out of range"):
        build_negative_response(UdsMessage(service_id=0x22, did=None, payload=b""), 0x100)


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


# ===========================================================================
# SID-specific validation tests
# ===========================================================================

class TestSidValidation:
    """validate_client_request() enforces per-SID rules."""

    def test_0x10_requires_sub_function(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="sub-function"):
            UdsMessage(0x10, None, b"").validate_client_request()

    def test_0x10_valid_sub_function(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x10, None, b"\x01").validate_client_request()

    def test_0x10_invalid_sub_function_range(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="out of valid range"):
            UdsMessage(0x10, None, b"\x00").validate_client_request()  # 0x00 invalid

    def test_0x11_invalid_reset_type(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="out of valid range"):
            UdsMessage(0x11, None, b"\x04").validate_client_request()

    def test_0x11_valid_reset_types(self) -> None:
        from udsdiag.uds import UdsMessage
        for rt in (0x01, 0x02, 0x03):
            UdsMessage(0x11, None, bytes([rt])).validate_client_request()

    def test_0x19_requires_sub_function(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="sub-function"):
            UdsMessage(0x19, None, b"").validate_client_request()

    def test_0x22_requires_did(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="requires a DID"):
            UdsMessage(0x22, None, b"").validate_client_request()

    def test_0x22_valid(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x22, 0xF190, b"").validate_client_request()

    def test_0x27_requires_sub_function(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="sub-function"):
            UdsMessage(0x27, None, b"").validate_client_request()

    def test_0x27_valid_seed_request(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x27, None, b"\x01").validate_client_request()  # seed (odd)

    def test_0x2e_requires_did(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="requires a DID"):
            UdsMessage(0x2E, None, b"\xAA").validate_client_request()

    def test_0x2e_requires_payload(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="non-empty payload"):
            UdsMessage(0x2E, 0xF187, b"").validate_client_request()

    def test_0x2e_valid(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x2E, 0xF187, b"\x12\x34").validate_client_request()

    def test_0x3e_valid_subfunc_0(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x3E, None, b"\x00").validate_client_request()

    def test_0x3e_valid_subfunc_1(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x3E, None, b"\x01").validate_client_request()

    def test_0x31_requires_sub_function(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="sub-function"):
            UdsMessage(0x31, None, b"").validate_client_request()

    def test_0x34_requires_payload(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="non-empty payload"):
            UdsMessage(0x34, None, b"").validate_client_request()

    def test_0x34_valid(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x34, None, b"\x00\x44\x00\x00\x10\x00\x00\x04").validate_client_request()

    def test_0x36_requires_payload(self) -> None:
        from udsdiag.uds import DiagnosticError, UdsMessage
        with pytest.raises(DiagnosticError, match="non-empty payload"):
            UdsMessage(0x36, None, b"").validate_client_request()

    def test_0x85_valid(self) -> None:
        from udsdiag.uds import UdsMessage
        UdsMessage(0x85, None, b"\x01").validate_client_request()


def test_subfunc_required_sid_without_range_entry() -> None:
    """SID in _SUBFUNC_REQUIRED but not in _SUBFUNC_RANGES: any non-empty payload passes."""
    from udsdiag.uds import UdsMessage
    # 0x28 CommunicationControl IS in _SUBFUNC_RANGES, use a sub-function value in range
    UdsMessage(0x28, None, b"\x00").validate_client_request()