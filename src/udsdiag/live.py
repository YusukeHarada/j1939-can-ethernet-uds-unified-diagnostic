from __future__ import annotations

import socket
import struct

from udsdiag.transport import EthernetFrame, J1939Frame
from udsdiag.uds import DiagnosticError

CAN_EFF_FLAG = 0x80000000


def send_ethernet_udp(frame: EthernetFrame) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.sendto(frame.payload, (frame.host, frame.port))


def send_socketcan_raw(frame: J1939Frame, interface: str) -> None:
    if not interface.strip():
        raise DiagnosticError("interface is required for live J1939 mode")
    af_can = getattr(socket, "AF_CAN", None)
    can_raw = getattr(socket, "CAN_RAW", None)
    if af_can is None or can_raw is None:
        raise DiagnosticError("SocketCAN is not supported on this platform")
    with socket.socket(af_can, socket.SOCK_RAW, can_raw) as can_socket:
        can_socket.bind((interface,))
        raw_payload = frame.payload[:8]
        packet = struct.pack("=IB3x8s", frame.can_id | CAN_EFF_FLAG, len(raw_payload), raw_payload)
        can_socket.send(packet)
