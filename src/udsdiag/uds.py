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

DEFAULT_NEGATIVE_RESPONSE_CODE = 0x11

# SIDs that require a sub-function byte (carried in payload[0])
_SUBFUNC_REQUIRED: frozenset[int] = frozenset(
    {0x10, 0x11, 0x19, 0x27, 0x28, 0x2A, 0x2C, 0x2F, 0x31, 0x3E, 0x85, 0x86, 0x87}
)

# Valid sub-function ranges per SID (inclusive).  None means any non-zero value.
_SUBFUNC_RANGES: dict[int, tuple[int, int]] = {
    0x10: (0x01, 0x7F),  # DiagnosticSessionControl
    0x11: (0x01, 0x03),  # ECUReset: hardReset / keyOffOnReset / softReset
    0x19: (0x01, 0x19),  # ReadDTCInformation sub-functions
    0x27: (0x01, 0x7E),  # SecurityAccess: seed (odd) / key (even)
    0x28: (0x00, 0x03),  # CommunicationControl
    0x2A: (0x01, 0x04),  # ReadDataByPeriodicIdentifier: rate
    0x2C: (0x01, 0x03),  # DynamicallyDefineDataIdentifier
    0x2F: (0x00, 0x0F),  # InputOutputControlByIdentifier: control parameter
    0x31: (0x01, 0x03),  # RoutineControl: start/stop/result
    0x3E: (0x00, 0x01),  # TesterPresent: 0x00 = respond, 0x01 = no response
    0x85: (0x01, 0x02),  # ControlDTCSetting: on / off
    0x86: (0x01, 0x06),  # ResponseOnEvent
    0x87: (0x01, 0x03),  # LinkControl
}

# SIDs that require a DID (2-byte data identifier)
_DID_REQUIRED: frozenset[int] = frozenset({0x22, 0x24, 0x2E, 0x2F})

# SIDs that require a non-empty payload (beyond SID + DID)
_PAYLOAD_REQUIRED: frozenset[int] = frozenset(
    {0x2E, 0x34, 0x35, 0x36, 0x3D, 0x84}
)


def _validate_sid_fields(message: UdsMessage) -> None:
    """Validate sub-function, DID, and payload requirements per SID."""
    sid = message.service_id

    # --- sub-function check ---
    if sid in _SUBFUNC_REQUIRED:
        if not message.payload:
            raise DiagnosticError(
                f"service 0x{sid:02X} requires a sub-function byte in payload"
            )
        sf = message.payload[0]
        if sid in _SUBFUNC_RANGES:  # pragma: no branch
            lo, hi = _SUBFUNC_RANGES[sid]
            if not (lo <= sf <= hi):
                raise DiagnosticError(
                    f"service 0x{sid:02X} sub-function 0x{sf:02X} out of valid range "
                    f"[0x{lo:02X}, 0x{hi:02X}]"
                )

    # --- DID check ---
    if sid in _DID_REQUIRED and message.did is None:
        raise DiagnosticError(
            f"service 0x{sid:02X} requires a DID (data identifier)"
        )

    # --- payload check ---
    if sid in _PAYLOAD_REQUIRED and not message.payload:
        raise DiagnosticError(
            f"service 0x{sid:02X} requires a non-empty payload"
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
        _validate_sid_fields(self)


def build_positive_response(request: UdsMessage, response_payload: bytes = b"") -> UdsMessage:
    request.validate_client_request()
    response_service_id = (request.service_id + 0x40) & 0xFF
    return UdsMessage(
        service_id=response_service_id,
        did=request.did,
        payload=response_payload,
    )


def build_negative_response(
    request: UdsMessage,
    response_code: int = DEFAULT_NEGATIVE_RESPONSE_CODE,
) -> UdsMessage:
    if response_code < 0 or response_code > 0xFF:
        raise DiagnosticError(f"negative response code out of range: {response_code}")
    return UdsMessage(
        service_id=0x7F,
        did=None,
        payload=bytes([request.service_id, response_code]),
    )


def build_server_response(
    request: UdsMessage,
    *,
    response_payload: bytes = b"",
    negative_response_code: int = DEFAULT_NEGATIVE_RESPONSE_CODE,
) -> UdsMessage:
    if request.service_id in CLIENT_SERVICE_IDS:
        return build_positive_response(request, response_payload=response_payload)
    return build_negative_response(request, response_code=negative_response_code)


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