from __future__ import annotations

from dataclasses import dataclass

from udsdiag.uds import DiagnosticError, UdsMessage, format_hex_bytes, parse_hex_bytes, parse_int

J1939_PRIORITY = 6
J1939_DEFAULT_PGN_BASE = 0xDA00
J1939_DEFAULT_SOURCE = 0xF9
J1939_DEFAULT_DESTINATION = 0xDA
ETHERNET_DEFAULT_HOST = "127.0.0.1"
ETHERNET_DEFAULT_PORT = 13400


@dataclass(frozen=True)
class J1939Frame:
    can_id: int
    pgn: int
    source_address: int
    destination_address: int
    payload: bytes


@dataclass(frozen=True)
class EthernetFrame:
    host: str
    port: int
    payload: bytes


def build_j1939_can_id(
    source_address: int = J1939_DEFAULT_SOURCE,
    destination_address: int = J1939_DEFAULT_DESTINATION,
    priority: int = J1939_PRIORITY,
) -> tuple[int, int]:
    pgn = J1939_DEFAULT_PGN_BASE + destination_address
    can_id = (priority << 26) | (pgn << 8) | source_address
    return can_id, pgn


def encode_j1939(
    message: UdsMessage,
    *,
    source_address: int = J1939_DEFAULT_SOURCE,
    destination_address: int = J1939_DEFAULT_DESTINATION,
) -> J1939Frame:
    can_id, pgn = build_j1939_can_id(source_address, destination_address)
    return J1939Frame(
        can_id=can_id,
        pgn=pgn,
        source_address=source_address,
        destination_address=destination_address,
        payload=message.to_payload(),
    )


def decode_j1939(frame: J1939Frame) -> UdsMessage:
    return UdsMessage.from_payload(frame.payload)


def encode_ethernet(
    message: UdsMessage,
    *,
    host: str = ETHERNET_DEFAULT_HOST,
    port: int = ETHERNET_DEFAULT_PORT,
) -> EthernetFrame:
    if not host.strip():
        raise DiagnosticError("host is required")
    return EthernetFrame(host=host, port=port, payload=message.to_payload())


def decode_ethernet(frame: EthernetFrame) -> UdsMessage:
    return UdsMessage.from_payload(frame.payload)


def j1939_to_row(frame: J1939Frame) -> dict[str, str]:
    return {
        "protocol": "j1939",
        "can_id": f"0x{frame.can_id:08X}",
        "pgn": f"0x{frame.pgn:04X}",
        "source_address": f"0x{frame.source_address:02X}",
        "destination_address": f"0x{frame.destination_address:02X}",
        "payload_hex": format_hex_bytes(frame.payload),
    }


def j1939_from_row(row: dict[str, str]) -> J1939Frame:
    protocol = row.get("protocol", "").strip().lower()
    if protocol != "j1939":
        raise DiagnosticError(f"protocol must be j1939: {protocol}")
    return J1939Frame(
        can_id=parse_int(row.get("can_id", ""), field="can_id", minimum=0, maximum=0x1FFFFFFF),
        pgn=parse_int(row.get("pgn", ""), field="pgn", minimum=0, maximum=0x3FFFF),
        source_address=parse_int(
            row.get("source_address", ""), field="source_address", minimum=0, maximum=0xFF
        ),
        destination_address=parse_int(
            row.get("destination_address", ""),
            field="destination_address",
            minimum=0,
            maximum=0xFF,
        ),
        payload=parse_hex_bytes(row.get("payload_hex", "")),
    )


def ethernet_to_row(frame: EthernetFrame) -> dict[str, str]:
    return {
        "protocol": "ethernet",
        "host": frame.host,
        "port": str(frame.port),
        "payload_hex": format_hex_bytes(frame.payload),
    }


def ethernet_from_row(row: dict[str, str]) -> EthernetFrame:
    protocol = row.get("protocol", "").strip().lower()
    if protocol != "ethernet":
        raise DiagnosticError(f"protocol must be ethernet: {protocol}")
    host = row.get("host", "").strip()
    if not host:
        raise DiagnosticError("host is required")
    port = parse_int(row.get("port", ""), field="port", minimum=1, maximum=65535)
    return EthernetFrame(host=host, port=port, payload=parse_hex_bytes(row.get("payload_hex", "")))
