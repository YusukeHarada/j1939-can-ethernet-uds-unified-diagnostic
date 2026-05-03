"""Tests for live.py: ISO 15765-2 segmentation and DoIP framing."""
from __future__ import annotations

import socket
import struct
from typing import cast

import pytest

from udsdiag.live import (
    _CAN_FRAME_FMT,
    _CAN_FRAME_LEN,
    _DOIP_HEADER_LEN,
    _DOIP_VERSION,
    _FC_CONTINUE,
    _ISOTP_CF,
    _ISOTP_FC,
    _ISOTP_FF,
    _ISOTP_SF,
    _PT_DIAG_MSG,
    _PT_DIAG_NEG_ACK,
    _PT_DIAG_POS_ACK,
    _PT_ROUTING_RESP,
    CAN_EFF_FLAG,
    _doip_header,
    _isotp_receive,
    _isotp_segments,
    _pack_can_frame,
    _recv_can_frame,
    exchange_doip,
    exchange_ethernet_udp,
    exchange_socketcan,
    send_ethernet_udp,
    send_socketcan_raw,
    serve_ethernet_udp,
)
from udsdiag.transport import EthernetFrame, J1939Frame
from udsdiag.uds import DiagnosticError

# ---------------------------------------------------------------------------
# Fake socket helpers
# ---------------------------------------------------------------------------

class FakeSocket:
    """Minimal socket stub for unit tests."""

    def __init__(self) -> None:
        self.bound: tuple[str, ...] | tuple[str, int] | None = None
        self.sent: list[bytes] = []
        self.sent_to: list[tuple[bytes, tuple[str, int]]] = []
        self.recv_queue: list[bytes] = []
        self.recvfrom_queue: list[tuple[bytes, tuple[str, int]]] = []
        self.timeout: float | None = None
        self.connected: tuple[str, int] | None = None

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def bind(self, addr: tuple[str, ...] | tuple[str, int]) -> None:
        self.bound = addr

    def connect(self, addr: tuple[str, int]) -> None:
        self.connected = addr

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent_to.append((data, addr))

    def recv(self, n: int) -> bytes:
        chunk = self.recv_queue.pop(0)
        return chunk[:n]

    def recvfrom(self, n: int) -> tuple[bytes, tuple[str, int]]:
        return self.recvfrom_queue.pop(0)

    def settimeout(self, t: float) -> None:
        self.timeout = t


def _make_can_frame(can_id: int, data: bytes) -> bytes:
    padded = data.ljust(8, b"\x00")[:8]
    return struct.pack(_CAN_FRAME_FMT, can_id | CAN_EFF_FLAG, len(data), padded)


def _make_doip(pt: int, payload: bytes) -> bytes:
    inv = (~_DOIP_VERSION) & 0xFF
    hdr = struct.pack(">BBHI", _DOIP_VERSION, inv, pt, len(payload))
    return hdr + payload


# ===========================================================================
# ISO 15765-2 segmentation tests
# ===========================================================================

class TestIsotpSegments:
    def test_single_frame_exact_7(self) -> None:
        payload = b"\x22\xf1\x90\x01\x02\x03\x04"
        segs = _isotp_segments(payload)
        assert len(segs) == 1
        assert segs[0][0] == (_ISOTP_SF << 4) | 7
        assert segs[0][1:8] == payload

    def test_single_frame_1_byte(self) -> None:
        segs = _isotp_segments(b"\x3E")
        assert len(segs) == 1
        assert segs[0][0] == 0x01   # SF | length=1
        assert segs[0][1] == 0x3E

    def test_single_frame_padding(self) -> None:
        segs = _isotp_segments(b"\x10\x01")
        assert len(segs) == 1
        assert len(segs[0]) == 8

    def test_multi_frame_8_bytes(self) -> None:
        payload = b"\x22" + b"\xAA" * 7   # 8 bytes -> FF + 1 CF
        segs = _isotp_segments(payload)
        assert len(segs) == 2
        # FF header
        ff_pci = (segs[0][0] << 8) | segs[0][1]
        assert (ff_pci >> 12) == _ISOTP_FF
        assert (ff_pci & 0x0FFF) == 8
        # CF header
        assert (segs[1][0] >> 4) == _ISOTP_CF
        assert (segs[1][0] & 0x0F) == 1   # SN=1

    def test_multi_frame_large_payload(self) -> None:
        payload = bytes(range(100))        # 100 bytes: FF + 14 CFs
        segs = _isotp_segments(payload)
        # FF carries 6 bytes, each CF carries 7 bytes
        assert len(segs) == 1 + 14        # ceil((100-6)/7) = 14

    def test_multi_frame_sn_wraps(self) -> None:
        # Enough bytes for SN to roll over from 0xF back to 0x0
        payload = bytes(range(6 + 7 * 16))  # FF + 16 CFs
        segs = _isotp_segments(payload)
        sns = [(s[0] & 0x0F) for s in segs[1:]]
        assert sns[:16] == list(range(1, 16)) + [0]

    def test_ff_length_field(self) -> None:
        payload = bytes(50)
        segs = _isotp_segments(payload)
        ff_len = ((segs[0][0] & 0x0F) << 8) | segs[0][1]
        assert ff_len == 50


# ===========================================================================
# CAN frame pack / unpack helpers
# ===========================================================================

class TestCanFrameHelpers:
    def test_pack_unpack_round_trip(self) -> None:
        raw = _pack_can_frame(0x7E0, b"\x02\x10\x01")
        assert len(raw) == _CAN_FRAME_LEN
        fake = FakeSocket()
        fake.recv_queue.append(raw)
        can_id, data = _recv_can_frame(cast(socket.socket, fake))
        assert can_id == 0x7E0
        assert data == b"\x02\x10\x01"

    def test_pack_output_is_can_frame_length(self) -> None:
        raw = _pack_can_frame(0x7E0, b"\x01\x02\x03")
        assert len(raw) == _CAN_FRAME_LEN


# ===========================================================================
# ISO 15765-2 reassembly tests
# ===========================================================================

class TestIsotpReceive:
    def _make_sf(self, can_id: int, payload: bytes) -> bytes:
        data = bytes([(_ISOTP_SF << 4) | len(payload)]) + payload
        return _make_can_frame(can_id, data)

    def _make_ff(self, can_id: int, total_len: int, first_data: bytes) -> bytes:
        hdr = struct.pack(">H", (_ISOTP_FF << 12) | (total_len & 0x0FFF))
        return _make_can_frame(can_id, hdr + first_data)

    def _make_cf(self, can_id: int, sn: int, data: bytes) -> bytes:
        return _make_can_frame(can_id, bytes([(_ISOTP_CF << 4) | (sn & 0x0F)]) + data)

    def test_single_frame(self) -> None:
        fake = FakeSocket()
        fake.recv_queue.append(self._make_sf(0x7E8, b"\x62\xF1\x90\xAB\xCD"))
        result = _isotp_receive(cast(socket.socket, fake), peer_can_id=0x7E8, own_can_id=0x7E0)
        assert result == b"\x62\xF1\x90\xAB\xCD"

    def test_ignores_unrelated_can_ids(self) -> None:
        fake = FakeSocket()
        fake.recv_queue.append(self._make_sf(0x123, b"\xFF"))   # noise
        fake.recv_queue.append(self._make_sf(0x7E8, b"\x62\xF1\x90"))
        result = _isotp_receive(cast(socket.socket, fake), peer_can_id=0x7E8, own_can_id=0x7E0)
        assert result == b"\x62\xF1\x90"

    def test_multi_frame_two_segments(self) -> None:
        # 8-byte payload: FF(6 bytes) + CF(2 bytes)
        payload = b"\x62\xF1\x90\x01\x02\x03\x04\x05"
        fake = FakeSocket()
        fake.recv_queue.append(self._make_ff(0x7E8, 8, payload[:6]))
        fake.recv_queue.append(self._make_cf(0x7E8, 1, payload[6:]))
        result = _isotp_receive(cast(socket.socket, fake), peer_can_id=0x7E8, own_can_id=0x7E0)
        assert result == payload
        # FC frame must have been sent
        assert len(fake.sent) == 1
        fc_raw = fake.sent[0]
        _, dlc, fc_data = struct.unpack(_CAN_FRAME_FMT, fc_raw)
        assert (fc_data[0] >> 4) == _ISOTP_FC
        assert (fc_data[0] & 0x0F) == _FC_CONTINUE

    def test_multi_frame_large(self) -> None:
        payload = bytes(range(50))
        segs = _isotp_segments(payload)
        fake = FakeSocket()
        for seg in segs:
            fake.recv_queue.append(_make_can_frame(0x7E8, seg))
        result = _isotp_receive(cast(socket.socket, fake), peer_can_id=0x7E8, own_can_id=0x7E0)
        assert result == payload

    def test_sequence_number_error(self) -> None:
        payload = bytes(range(20))
        segs = _isotp_segments(payload)
        # Corrupt the SN of the second CF
        bad_cf = bytearray(segs[2])
        bad_cf[0] = (_ISOTP_CF << 4) | 0x0F  # wrong SN
        fake = FakeSocket()
        fake.recv_queue.append(_make_can_frame(0x7E8, bytes(segs[0])))
        fake.recv_queue.append(_make_can_frame(0x7E8, bytes(segs[1])))
        fake.recv_queue.append(_make_can_frame(0x7E8, bytes(bad_cf)))
        with pytest.raises(DiagnosticError, match="sequence error"):
            _isotp_receive(cast(socket.socket, fake), peer_can_id=0x7E8, own_can_id=0x7E0)

    def test_unexpected_pci_type(self) -> None:
        bad = _make_can_frame(0x7E8, bytes([0xA0]))  # PCI type 0xA = unknown
        fake = FakeSocket()
        fake.recv_queue.append(bad)
        with pytest.raises(DiagnosticError, match="PCI type"):
            _isotp_receive(cast(socket.socket, fake), peer_can_id=0x7E8, own_can_id=0x7E0)


# ===========================================================================
# send_socketcan_raw (uses _isotp_segments)
# ===========================================================================

class TestSendSocketcanRaw:
    def test_single_frame_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        monkeypatch.setattr("udsdiag.live.socket.AF_CAN", 29, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.CAN_RAW", 1, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        send_socketcan_raw(J1939Frame(0x18DADAF9, 0xDADA, 0xF9, 0xDA, b"\x02\x10\x01"), "can0")

        assert len(fake.sent) == 1
        raw = fake.sent[0]
        assert len(raw) == _CAN_FRAME_LEN   # always 16-byte SocketCAN frame
        _, _, frame_data = struct.unpack(_CAN_FRAME_FMT, raw)
        # SF: first byte = PCI (0x0N where N=payload_len), then payload
        assert frame_data[0] == (_ISOTP_SF << 4) | 3   # length=3
        assert frame_data[1:4] == b"\x02\x10\x01"

    def test_multi_frame_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        monkeypatch.setattr("udsdiag.live.socket.AF_CAN", 29, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.CAN_RAW", 1, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        long_payload = b"\x22" + bytes(range(20))  # 21 bytes -> FF + CFs
        send_socketcan_raw(J1939Frame(0x7E0, 0xDA00, 0xF9, 0xDA, long_payload), "can0")

        assert len(fake.sent) > 1   # more than just a single frame

    def test_requires_interface(self) -> None:
        with pytest.raises(DiagnosticError, match="interface is required"):
            send_socketcan_raw(J1939Frame(0, 0, 0, 0, b""), " ")

    def test_unsupported_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delattr("udsdiag.live.socket.AF_CAN", raising=False)
        monkeypatch.delattr("udsdiag.live.socket.CAN_RAW", raising=False)
        with pytest.raises(DiagnosticError, match="SocketCAN is not supported"):
            send_socketcan_raw(J1939Frame(0, 0, 0, 0, b""), "can0")


# ===========================================================================
# exchange_socketcan
# ===========================================================================

class TestExchangeSocketcan:
    def test_single_frame_request_and_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        # Enqueue a SF response: 0x62 0xF1 0x90
        sf_resp = bytes([(_ISOTP_SF << 4) | 3, 0x62, 0xF1, 0x90]).ljust(8, b"\x00")
        fake.recv_queue.append(_make_can_frame(0x7E8, sf_resp))

        monkeypatch.setattr("udsdiag.live.socket.AF_CAN", 29, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.CAN_RAW", 1, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        result = exchange_socketcan(
            J1939Frame(0x7E0, 0xDA00, 0xF9, 0xDA, b"\x22\xF1\x90"),
            interface="can0",
            response_can_id=0x7E8,
            timeout=1.0,
        )
        assert result == b"\x62\xF1\x90"
        assert fake.timeout == 1.0

    def test_multi_frame_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = bytes(range(20))
        segs = _isotp_segments(payload)
        fake = FakeSocket()
        for seg in segs:
            fake.recv_queue.append(_make_can_frame(0x7E8, seg))

        monkeypatch.setattr("udsdiag.live.socket.AF_CAN", 29, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.CAN_RAW", 1, raising=False)
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        result = exchange_socketcan(
            J1939Frame(0x7E0, 0xDA00, 0xF9, 0xDA, b"\x22\xF1\x90"),
            interface="can0",
            response_can_id=0x7E8,
        )
        assert result == payload


# ===========================================================================
# DoIP internal helpers
# ===========================================================================

class TestDoipHelpers:
    def test_doip_header_structure(self) -> None:
        hdr = _doip_header(0x8001, 10)
        ver, inv, pt, pl_len = struct.unpack(">BBHI", hdr)
        assert ver == _DOIP_VERSION
        assert inv == (~_DOIP_VERSION) & 0xFF
        assert pt == 0x8001
        assert pl_len == 10


# ===========================================================================
# exchange_doip
# ===========================================================================

class TestExchangeDoip:
    def _make_routing_resp(self, code: int = 0x10) -> bytes:
        # payload: client_la(2) + ecu_la(2) + logical_addr(2) + OEM(2) + code(1)
        body = struct.pack(">HHHHb", 0x0E00, 0x0001, 0x0E00, 0x0001, code)
        return _make_doip(_PT_ROUTING_RESP, body)

    def _make_diag_resp(self, uds_payload: bytes) -> bytes:
        body = struct.pack(">HH", 0x0001, 0x0E00) + uds_payload
        return _make_doip(_PT_DIAG_MSG, body)

    def _setup_fake(self, fake: FakeSocket, responses: list[bytes]) -> None:
        for chunk in responses:
            # Split into header + payload to simulate _recv_exactly behaviour
            fake.recv_queue.extend([chunk[:_DOIP_HEADER_LEN], chunk[_DOIP_HEADER_LEN:]])

    def test_successful_exchange(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        self._setup_fake(fake, [
            self._make_routing_resp(0x10),
            self._make_diag_resp(b"\x62\xF1\x90\xAB\xCD"),
        ])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        result = exchange_doip(
            EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
            source_address=0x0E00,
            target_address=0x0001,
        )
        assert result == b"\x62\xF1\x90\xAB\xCD"

    def test_skips_positive_ack(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        pos_ack = _make_doip(_PT_DIAG_POS_ACK, b"\x0E\x00\x00\x01\x00")
        self._setup_fake(fake, [
            self._make_routing_resp(0x10),
            pos_ack,
            self._make_diag_resp(b"\x62\xF1\x90"),
        ])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        result = exchange_doip(
            EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
            source_address=0x0E00,
            target_address=0x0001,
        )
        assert result == b"\x62\xF1\x90"

    def test_negative_ack_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        neg_ack = _make_doip(_PT_DIAG_NEG_ACK, b"\x0E\x00\x00\x01\x02")
        self._setup_fake(fake, [self._make_routing_resp(0x10), neg_ack])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="Negative ACK"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )

    def test_unexpected_payload_type_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        bad = _make_doip(0x9999, b"\x00")
        self._setup_fake(fake, [self._make_routing_resp(0x10), bad])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="unexpected payload type"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )

    def test_routing_wrong_payload_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        bad = _make_doip(0x0001, b"\x00" * 9)
        self._setup_fake(fake, [bad])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="expected Routing Activation Response"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )

    def test_routing_too_short(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        short = _make_doip(_PT_ROUTING_RESP, b"\x00" * 8)   # < 9 bytes
        self._setup_fake(fake, [short])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="too short"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )

    def test_routing_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        self._setup_fake(fake, [self._make_routing_resp(code=0x00)])  # denied
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="denied"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )

    def test_connection_refused_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def bad_connect(addr: tuple[str, int]) -> None:
            raise OSError("Connection refused")

        fake = FakeSocket()
        fake.connect = bad_connect  # type: ignore[method-assign]
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="cannot connect"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )

    def test_connection_closed_mid_recv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        fake.recv_queue.append(b"")   # EOF immediately
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)

        with pytest.raises(DiagnosticError, match="connection closed"):
            exchange_doip(
                EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"),
                source_address=0x0E00,
                target_address=0x0001,
            )


# ===========================================================================
# UDP helpers (unchanged behaviour)
# ===========================================================================

class TestUdpHelpers:
    def test_send_ethernet_udp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)
        send_ethernet_udp(EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"))
        assert fake.sent_to == [(b"\x22\xF1\x90", ("127.0.0.1", 13400))]

    def test_exchange_ethernet_udp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        fake.recvfrom_queue.append((b"\x62\xF1\x90", ("127.0.0.1", 13400)))
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)
        result = exchange_ethernet_udp(EthernetFrame("127.0.0.1", 13400, b"\x22\xF1\x90"), 0.5)
        assert result == b"\x62\xF1\x90"
        assert fake.timeout == 0.5

    def test_serve_ethernet_udp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeSocket()
        fake.recvfrom_queue.extend([
            (b"one", ("127.0.0.1", 50000)),
            (b"two", ("127.0.0.1", 50001)),
        ])
        monkeypatch.setattr("udsdiag.live.socket.socket", lambda *a: fake)
        handled = serve_ethernet_udp(
            "127.0.0.1", 13400, lambda p: p.upper(), max_messages=2
        )
        assert handled == 2
        assert fake.sent_to == [
            (b"ONE", ("127.0.0.1", 50000)),
            (b"TWO", ("127.0.0.1", 50001)),
        ]

    def test_serve_requires_host(self) -> None:
        with pytest.raises(DiagnosticError, match="host is required"):
            serve_ethernet_udp(" ", 13400, lambda p: p, max_messages=1)

    def test_serve_requires_positive_max(self) -> None:
        with pytest.raises(DiagnosticError, match="max_messages must be at least 1"):
            serve_ethernet_udp("127.0.0.1", 13400, lambda p: p, max_messages=0)