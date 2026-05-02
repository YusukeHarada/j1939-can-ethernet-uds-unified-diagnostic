from __future__ import annotations

import pytest

from udsdiag.transport import (
    ETHERNET_DEFAULT_HOST,
    ETHERNET_DEFAULT_PORT,
    J1939_DEFAULT_DESTINATION,
    J1939_DEFAULT_SOURCE,
    EthernetFrame,
    J1939Frame,
    build_j1939_can_id,
    decode_ethernet,
    decode_j1939,
    encode_ethernet,
    encode_j1939,
    ethernet_from_row,
    ethernet_to_row,
    j1939_from_row,
    j1939_to_row,
)
from udsdiag.uds import DiagnosticError, UdsMessage


def test_j1939_frame_round_trip() -> None:
    message = UdsMessage(service_id=0x22, did=0xF190, payload=b"")
    can_id, pgn = build_j1939_can_id(J1939_DEFAULT_SOURCE, J1939_DEFAULT_DESTINATION)

    frame = encode_j1939(message)
    row = j1939_to_row(frame)

    assert frame == J1939Frame(
        can_id=can_id,
        pgn=pgn,
        source_address=J1939_DEFAULT_SOURCE,
        destination_address=J1939_DEFAULT_DESTINATION,
        payload=b"\x22\xf1\x90",
    )
    assert decode_j1939(j1939_from_row(row)) == message


def test_ethernet_frame_round_trip() -> None:
    message = UdsMessage(service_id=0x2E, did=0xF187, payload=b"\x12\x34")

    frame = encode_ethernet(message)
    row = ethernet_to_row(frame)

    assert frame == EthernetFrame(
        host=ETHERNET_DEFAULT_HOST,
        port=ETHERNET_DEFAULT_PORT,
        payload=b"\x2e\xf1\x87\x12\x34",
    )
    assert decode_ethernet(ethernet_from_row(row)) == message


def test_custom_ethernet_frame() -> None:
    frame = encode_ethernet(UdsMessage(0x10, None, b"\x03"), host="192.0.2.10", port=13401)

    assert ethernet_to_row(frame) == {
        "protocol": "ethernet",
        "host": "192.0.2.10",
        "port": "13401",
        "payload_hex": "10 03",
    }


@pytest.mark.parametrize(
    "row",
    [
        {"protocol": "ethernet", "host": "", "port": "13400", "payload_hex": "22"},
        {"protocol": "j1939", "host": "127.0.0.1", "port": "13400", "payload_hex": "22"},
    ],
)
def test_ethernet_from_row_errors(row: dict[str, str]) -> None:
    with pytest.raises(DiagnosticError):
        ethernet_from_row(row)


def test_encode_ethernet_requires_host() -> None:
    with pytest.raises(DiagnosticError, match="host is required"):
        encode_ethernet(UdsMessage(0x22, None, b""), host=" ")


def test_j1939_from_row_rejects_wrong_protocol() -> None:
    with pytest.raises(DiagnosticError, match="protocol must be j1939"):
        j1939_from_row(
            {
                "protocol": "ethernet",
                "can_id": "0",
                "pgn": "0",
                "source_address": "0",
                "destination_address": "0",
                "payload_hex": "22",
            }
        )
