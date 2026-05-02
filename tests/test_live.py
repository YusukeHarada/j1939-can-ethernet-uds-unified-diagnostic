from __future__ import annotations

import socket

import pytest

from udsdiag.live import CAN_EFF_FLAG, send_ethernet_udp, send_socketcan_raw
from udsdiag.transport import EthernetFrame, J1939Frame
from udsdiag.uds import DiagnosticError


class FakeSocket:
    def __init__(self) -> None:
        self.bound: tuple[str, ...] | None = None
        self.sent_to: tuple[bytes, tuple[str, int]] | None = None
        self.sent: bytes | None = None

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def bind(self, address: tuple[str, ...]) -> None:
        self.bound = address

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent_to = (payload, address)

    def send(self, payload: bytes) -> None:
        self.sent = payload


def test_send_ethernet_udp(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket()

    def socket_factory(family: int, sock_type: int) -> FakeSocket:
        assert family == socket.AF_INET
        assert sock_type == socket.SOCK_DGRAM
        return fake

    monkeypatch.setattr("udsdiag.live.socket.socket", socket_factory)

    send_ethernet_udp(EthernetFrame(host="127.0.0.1", port=13400, payload=b"abc"))

    assert fake.sent_to == (b"abc", ("127.0.0.1", 13400))


def test_send_socketcan_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket()
    monkeypatch.setattr("udsdiag.live.socket.AF_CAN", 29, raising=False)
    monkeypatch.setattr("udsdiag.live.socket.CAN_RAW", 1, raising=False)

    def socket_factory(family: int, sock_type: int, protocol: int) -> FakeSocket:
        assert family == 29
        assert sock_type == socket.SOCK_RAW
        assert protocol == 1
        return fake

    monkeypatch.setattr("udsdiag.live.socket.socket", socket_factory)

    send_socketcan_raw(J1939Frame(0x18DADAF9, 0xDADA, 0xF9, 0xDA, b"123456789"), "can0")

    assert fake.bound == ("can0",)
    assert fake.sent is not None
    assert int.from_bytes(fake.sent[:4], "little") == (0x18DADAF9 | CAN_EFF_FLAG)
    assert fake.sent[4] == 8


def test_send_socketcan_raw_requires_interface() -> None:
    with pytest.raises(DiagnosticError, match="interface is required"):
        send_socketcan_raw(J1939Frame(0, 0, 0, 0, b""), " ")


def test_send_socketcan_raw_reports_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr("udsdiag.live.socket.AF_CAN", raising=False)
    monkeypatch.delattr("udsdiag.live.socket.CAN_RAW", raising=False)

    with pytest.raises(DiagnosticError, match="SocketCAN is not supported"):
        send_socketcan_raw(J1939Frame(0, 0, 0, 0, b""), "can0")
