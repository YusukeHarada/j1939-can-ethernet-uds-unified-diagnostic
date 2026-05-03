"""Live transport implementations.

J1939 / SocketCAN
-----------------
Implements ISO 15765-2 transport layer segmentation:
  - Single Frame  (SF, PCI type 0): payload <= 7 bytes
  - First Frame   (FF, PCI type 1): start of multi-frame sequence
  - Consecutive Frame (CF, PCI type 2): continuation frames
  - Flow Control  (FC, PCI type 3): receiver grants transmission

Ethernet / DoIP
---------------
Implements ISO 13400-2 (DoIP) over TCP:
  - Routing Activation Request / Response
  - Diagnostic Message (UDS payload wrapped in DoIP header)
  - Positive / Negative Acknowledgement handling
"""
from __future__ import annotations

import socket
import struct
from collections.abc import Callable

from udsdiag.transport import EthernetFrame, J1939Frame
from udsdiag.uds import DiagnosticError

# ---------------------------------------------------------------------------
# SocketCAN / ISO 15765-2 constants
# ---------------------------------------------------------------------------
CAN_EFF_FLAG = 0x80000000
CAN_MAX_DLEN = 8
_ISOTP_SF = 0x0
_ISOTP_FF = 0x1
_ISOTP_CF = 0x2
_ISOTP_FC = 0x3
_FC_CONTINUE = 0x00

_CAN_FRAME_FMT = "=IB3x8s"
_CAN_FRAME_LEN = struct.calcsize(_CAN_FRAME_FMT)  # 16 bytes

# ---------------------------------------------------------------------------
# DoIP / ISO 13400-2 constants
# ---------------------------------------------------------------------------
_DOIP_VERSION = 0x02
_DOIP_HEADER_LEN = 8
_PT_ROUTING_REQ = 0x0005
_PT_ROUTING_RESP = 0x0006
_PT_DIAG_MSG = 0x8001
_PT_DIAG_POS_ACK = 0x8002
_PT_DIAG_NEG_ACK = 0x8003
_ROUTING_ACTIVATION_DEFAULT = 0x00
_ROUTING_SUCCESS_CODES = frozenset({0x10, 0x11})
_DOIP_TCP_BUFSIZE = 4096


# ===========================================================================
# SocketCAN internal helpers
# ===========================================================================

def _can_socket(interface: str) -> socket.socket:
    if not interface.strip():
        raise DiagnosticError("interface is required for live J1939 mode")
    af_can = getattr(socket, "AF_CAN", None)
    can_raw = getattr(socket, "CAN_RAW", None)
    if af_can is None or can_raw is None:
        raise DiagnosticError("SocketCAN is not supported on this platform")
    sock = socket.socket(af_can, socket.SOCK_RAW, can_raw)
    sock.bind((interface,))
    return sock


def _pack_can_frame(can_id: int, data: bytes) -> bytes:
    padded = data.ljust(CAN_MAX_DLEN, b"\x00")[:CAN_MAX_DLEN]
    return struct.pack(_CAN_FRAME_FMT, can_id | CAN_EFF_FLAG, len(data), padded)


def _recv_can_frame(sock: socket.socket) -> tuple[int, bytes]:
    raw = sock.recv(_CAN_FRAME_LEN)
    can_id, dlc, data = struct.unpack(_CAN_FRAME_FMT, raw)
    can_id &= 0x1FFFFFFF
    return can_id, bytes(data[:dlc])


def _isotp_segments(payload: bytes) -> list[bytes]:
    """Segment payload into ISO 15765-2 CAN data fields (8 bytes each)."""
    length = len(payload)
    if length <= 7:
        return [(bytes([(_ISOTP_SF << 4) | length]) + payload).ljust(8, b"\x00")]

    frames: list[bytes] = []
    ff_header = struct.pack(">H", (_ISOTP_FF << 12) | (length & 0x0FFF))
    frames.append((ff_header + payload[:6]).ljust(8, b"\x00"))
    remaining = payload[6:]
    sn = 1
    while remaining:
        chunk = remaining[:7]
        frames.append(
            (bytes([(_ISOTP_CF << 4) | (sn & 0x0F)]) + chunk).ljust(8, b"\x00")
        )
        remaining = remaining[7:]
        sn = (sn + 1) & 0x0F
    return frames


def _isotp_receive(sock: socket.socket, peer_can_id: int, own_can_id: int) -> bytes:
    """Reassemble an ISO 15765-2 message from peer_can_id."""
    buf = b""
    expected_length = 0
    sn_expected = 1

    while True:
        can_id, data = _recv_can_frame(sock)
        if can_id != peer_can_id:
            continue

        pci_type = (data[0] >> 4) & 0x0F

        if pci_type == _ISOTP_SF:
            length = data[0] & 0x0F
            return data[1: 1 + length]

        if pci_type == _ISOTP_FF:
            expected_length = ((data[0] & 0x0F) << 8) | data[1]
            buf = data[2:]
            fc_data = bytes([(_ISOTP_FC << 4) | _FC_CONTINUE, 0x00, 0x00])
            sock.send(_pack_can_frame(own_can_id | CAN_EFF_FLAG, fc_data))

        elif pci_type == _ISOTP_CF:
            sn = data[0] & 0x0F
            if sn != sn_expected:
                raise DiagnosticError(
                    f"ISO 15765-2 sequence error: expected SN {sn_expected}, got {sn}"
                )
            buf += data[1:]
            sn_expected = (sn_expected + 1) & 0x0F
            if len(buf) >= expected_length:
                return buf[:expected_length]

        else:
            raise DiagnosticError(f"Unexpected ISO 15765-2 PCI type: 0x{pci_type:X}")


# ===========================================================================
# Public J1939 / SocketCAN API
# ===========================================================================

def send_socketcan_raw(frame: J1939Frame, interface: str) -> None:
    """Transmit frame as ISO 15765-2 segment(s) on interface."""
    sock = _can_socket(interface)
    with sock:
        for seg in _isotp_segments(frame.payload):
            sock.send(_pack_can_frame(frame.can_id, seg))


def exchange_socketcan(
    frame: J1939Frame,
    interface: str,
    response_can_id: int,
    timeout: float = 2.0,
) -> bytes:
    """Transmit frame and return the reassembled UDS response payload."""
    sock = _can_socket(interface)
    with sock:
        sock.settimeout(timeout)
        for seg in _isotp_segments(frame.payload):
            sock.send(_pack_can_frame(frame.can_id, seg))
        return _isotp_receive(sock, response_can_id, frame.can_id)


# ===========================================================================
# DoIP / ISO 13400-2 internal helpers
# ===========================================================================

def _doip_header(payload_type: int, payload_length: int) -> bytes:
    inv = (~_DOIP_VERSION) & 0xFF
    return struct.pack(">BBHI", _DOIP_VERSION, inv, payload_type, payload_length)


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise DiagnosticError("DoIP: connection closed unexpectedly")
        buf += chunk
    return buf


def _doip_recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    hdr = _recv_exactly(sock, _DOIP_HEADER_LEN)
    _, _, pt, pl_len = struct.unpack(">BBHI", hdr)
    payload = _recv_exactly(sock, pl_len)
    return pt, payload


def _doip_routing_activation(sock: socket.socket, source_address: int) -> None:
    body = struct.pack(">HBl", source_address, _ROUTING_ACTIVATION_DEFAULT, 0)
    sock.sendall(_doip_header(_PT_ROUTING_REQ, len(body)) + body)
    pt, payload = _doip_recv_frame(sock)
    if pt != _PT_ROUTING_RESP:
        raise DiagnosticError(
            f"DoIP: expected Routing Activation Response (0x{_PT_ROUTING_RESP:04X}), "
            f"got 0x{pt:04X}"
        )
    if len(payload) < 9:
        raise DiagnosticError("DoIP: Routing Activation Response too short")
    code = payload[8]
    if code not in _ROUTING_SUCCESS_CODES:
        raise DiagnosticError(f"DoIP: Routing Activation denied (code=0x{code:02X})")


def _doip_send_diagnostic(
    sock: socket.socket,
    source_address: int,
    target_address: int,
    uds_payload: bytes,
) -> None:
    body = struct.pack(">HH", source_address, target_address) + uds_payload
    sock.sendall(_doip_header(_PT_DIAG_MSG, len(body)) + body)


def _doip_recv_diagnostic(sock: socket.socket) -> bytes:
    while True:
        pt, payload = _doip_recv_frame(sock)
        if pt == _PT_DIAG_POS_ACK:
            continue
        if pt == _PT_DIAG_NEG_ACK:
            raise DiagnosticError("DoIP: Diagnostic Message Negative ACK")
        if pt == _PT_DIAG_MSG:
            return payload[4:]
        raise DiagnosticError(f"DoIP: unexpected payload type 0x{pt:04X}")


# ===========================================================================
# Public Ethernet / DoIP API
# ===========================================================================

def send_ethernet_udp(frame: EthernetFrame) -> None:
    """Send frame payload as a UDP datagram (simulate / batch mode)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(frame.payload, (frame.host, frame.port))


def exchange_ethernet_udp(frame: EthernetFrame, timeout_seconds: float) -> bytes:
    """Send frame via UDP and return the first response datagram."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendto(frame.payload, (frame.host, frame.port))
        payload, _address = sock.recvfrom(_DOIP_TCP_BUFSIZE)
        return payload


def exchange_doip(
    frame: EthernetFrame,
    source_address: int,
    target_address: int,
    timeout: float = 2.0,
) -> bytes:
    """Send frame payload as a DoIP Diagnostic Message (TCP) and return UDS response."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((frame.host, frame.port))
        except OSError as exc:
            raise DiagnosticError(
                f"DoIP: cannot connect to {frame.host}:{frame.port}: {exc}"
            ) from exc
        _doip_routing_activation(sock, source_address)
        _doip_send_diagnostic(sock, source_address, target_address, frame.payload)
        return _doip_recv_diagnostic(sock)


def serve_ethernet_udp(
    host: str,
    port: int,
    handler: Callable[[bytes], bytes],
    *,
    max_messages: int | None = None,
) -> int:
    """UDP server loop for simulation / testing."""
    if not host.strip():
        raise DiagnosticError("host is required")
    if max_messages is not None and max_messages < 1:
        raise DiagnosticError("max_messages must be at least 1")
    handled = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((host, port))
        while max_messages is None or handled < max_messages:
            payload, address = sock.recvfrom(_DOIP_TCP_BUFSIZE)
            response = handler(payload)
            sock.sendto(response, address)
            handled += 1
    return handled