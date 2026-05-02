from __future__ import annotations

from dataclasses import dataclass


class DiagnosticError(ValueError):
    """Raised when diagnostic CSV or payload data is invalid."""


CLIENT_SERVICE_IDS = frozenset(
    {
        0x10,
        0x11,
        0x14,
        0x19,
        0x22,
        0x23,
        0x24,
        0x27,
        0x28,
        0x2A,
        0x2C,
        0x2E,
        0x2F,
        0x31,
        0x34,
        0x35,
        0x36,
        0x37,
        0x38,
        0x3D,
        0x3E,
        0x83,
        0x84,
        0x85,
        0x86,
        0x87,
    }
)


@dataclass(frozen=True)
class UdsMessage:
    service_id: int
    did: int | None
    payload: bytes

    def to_payload(self) -> bytes:
        head = bytes([self.service_id])
        if self.did is None:
            return head + self.payload
        return head + self.did.to_bytes(2, "big") + self.payload

    @classmethod
    def from_payload(cls, data: bytes) -> UdsMessage:
        if not data:
            raise DiagnosticError("UDS payload is empty")
        did = int.from_bytes(data[1:3], "big") if len(data) >= 3 else None
        payload = data[3:] if did is not None else data[1:]
        return cls(service_id=data[0], did=did, payload=payload)

    def status(self) -> str:
        if self.service_id == 0x7F:
            return "negative_response"
        if self.service_id >= 0x40:
            return "positive_response"
        return "request"

    def validate_client_request(self) -> None:
        if self.service_id not in CLIENT_SERVICE_IDS:
            raise DiagnosticError(
                f"service_id is not a supported UDS client request: 0x{self.service_id:02X}"
            )


def parse_int(text: str, *, field: str, minimum: int, maximum: int) -> int:
    stripped = text.strip()
    if not stripped:
        raise DiagnosticError(f"{field} is required")
    try:
        value = int(stripped, 0)
    except ValueError as exc:
        raise DiagnosticError(f"{field} must be an integer: {text}") from exc
    if value < minimum or value > maximum:
        raise DiagnosticError(f"{field} out of range: {text}")
    return value


def parse_optional_int(text: str, *, field: str, minimum: int, maximum: int) -> int | None:
    if not text.strip():
        return None
    return parse_int(text, field=field, minimum=minimum, maximum=maximum)


def parse_hex_bytes(text: str) -> bytes:
    stripped = text.replace(" ", "").replace("_", "").strip()
    if not stripped:
        return b""
    if len(stripped) % 2 != 0:
        raise DiagnosticError(f"payload_hex must contain pairs of hex digits: {text}")
    try:
        return bytes.fromhex(stripped)
    except ValueError as exc:
        raise DiagnosticError(f"payload_hex contains non-hex data: {text}") from exc


def format_hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def uds_from_row(row: dict[str, str]) -> UdsMessage:
    service_id = parse_int(row.get("service_id", ""), field="service_id", minimum=0, maximum=0xFF)
    did = parse_optional_int(row.get("did", ""), field="did", minimum=0, maximum=0xFFFF)
    payload = parse_hex_bytes(row.get("payload_hex", ""))
    return UdsMessage(service_id=service_id, did=did, payload=payload)


def uds_to_row(message: UdsMessage) -> dict[str, str]:
    did = "" if message.did is None else f"0x{message.did:04X}"
    return {
        "service_id": f"0x{message.service_id:02X}",
        "did": did,
        "payload_hex": format_hex_bytes(message.payload),
        "status": message.status(),
    }
