from __future__ import annotations

import socket

import pytest

from udsdiag.live import (
    CAN_EFF_FLAG,
    exchange_ethernet_udp,
    send_ethernet_udp,
    send_socketcan_raw,
    serve_ethernet_udp,
)
from udsdiag.transport import EthernetFrame, J1939Frame
from udsdiag.uds import DiagnosticError


class FakeSocket:
    def __init__(self) -> None:
        self.bound: tuple[str, ...] | tuple[str, int] | None = None
        self.sent_to: tuple[bytes, tuple[str, int]] | None = None
        self.sent_to_all: list[tuple[bytes, tuple[str, int]]] = []
        self.sent: bytes | None = None
        self.timeout: float | None = None
        self.received: list[tuple[bytes, tuple[str, int]]] = []

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def bind(self, address: tuple[str, ...] | tuple[str, int]) -> None:
        self.bound = address

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent_to = (payload, address)
        self.sent_to_all.append((payload, address))

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        assert size == 4096
        return self.received.pop(0)

    def send(self, payload: bytes) -> None:
        self.sent = payload

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


def test_send_ethernet_udp(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket()

    def socket_factory(family: int, sock_type: int) -> FakeSocket:
        assert family == socket.AF_INET
        assert sock_type == socket.SOCK_DGRAM
        return fake

    monkeypatch.setattr("udsdiag.live.socket.socket", socket_factory)

    send_ethernet_udp(EthernetFrame(host="127.0.0.1", port=13400, payload=b"abc"))

    assert fake.sent_to == (b"abc", ("127.0.0.1", 13400))


def test_exchange_ethernet_udp(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket()
    fake.received.append((b"\x62\xf1\x90", ("127.0.0.1", 13400)))

    def socket_factory(family: int, sock_type: int) -> FakeSocket:
        assert family == socket.AF_INET
        assert sock_type == socket.SOCK_DGRAM
        return fake

    monkeypatch.setattr("udsdiag.live.socket.socket", socket_factory)

    response = exchange_ethernet_udp(EthernetFrame("127.0.0.1", 13400, b"\x22\xf1\x90"), 0.5)

    assert response == b"\x62\xf1\x90"
    assert fake.timeout == 0.5
    assert fake.sent_to == (b"\x22\xf1\x90", ("127.0.0.1", 13400))


def test_serve_ethernet_udp(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSocket()
    fake.received.extend(
        [
            (b"one", ("127.0.0.1", 50000)),
            (b"two", ("127.0.0.1", 50001)),
        ]
    )

    def socket_factory(family: int, sock_type: int) -> FakeSocket:
        assert family == socket.AF_INET
        assert sock_type == socket.SOCK_DGRAM
        return fake

    monkeypatch.setattr("udsdiag.live.socket.socket", socket_factory)

    handled = serve_ethernet_udp(
        "127.0.0.1",
        13400,
        lambda payload: payload.upper(),
        max_messages=2,
    )

    assert handled == 2
    assert fake.bound == ("127.0.0.1", 13400)
    assert fake.sent_to_all == [
        (b"ONE", ("127.0.0.1", 50000)),
        (b"TWO", ("127.0.0.1", 50001)),
    ]


def test_serve_ethernet_udp_validates_arguments() -> None:
    with pytest.raises(DiagnosticError, match="host is required"):
        serve_ethernet_udp(" ", 13400, lambda payload: payload, max_messages=1)

    with pytest.raises(DiagnosticError, match="max_messages must be at least 1"):
        serve_ethernet_udp("127.0.0.1", 13400, lambda payload: payload, max_messages=0)


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
