from __future__ import annotations

import csv
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

import pytest

from udsdiag.cli import main, run
from udsdiag.transport import EthernetFrame
from udsdiag.uds import DiagnosticError


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_uds(path: Path) -> None:
    path.write_text(
        "service_id,did,payload_hex\n"
        "0x22,0xF190,\n"
        "0x2E,0xF187,12 34\n"
        "0x7F,,22 31\n",
        encoding="utf-8",
    )


def test_cli_send_receive_j1939(tmp_path: Path) -> None:
    uds = tmp_path / "uds.csv"
    frames = tmp_path / "frames.csv"
    decoded = tmp_path / "decoded.csv"
    write_uds(uds)

    assert (
        main(["send", "--transport", "j1939", "--input", str(uds), "--output", str(frames)])
        == 0
    )
    assert rows(frames)[0]["protocol"] == "j1939"

    assert (
        main(["receive", "--transport", "j1939", "--input", str(frames), "--output", str(decoded)])
        == 0
    )

    decoded_rows = rows(decoded)
    assert decoded_rows[0]["service_id"] == "0x22"
    assert decoded_rows[1]["payload_hex"] == "12 34"
    assert decoded_rows[2]["status"] == "negative_response"


def test_cli_client_j1939_accepts_client_requests(tmp_path: Path) -> None:
    uds = tmp_path / "uds.csv"
    frames = tmp_path / "frames.csv"
    uds.write_text(
        "service_id,did,payload_hex\n"
        "0x22,0xF190,\n"
        "0x85,,02\n",
        encoding="utf-8",
    )

    assert (
        main(["client", "--transport", "j1939", "--input", str(uds), "--output", str(frames)])
        == 0
    )

    frame_rows = rows(frames)
    assert frame_rows[0]["payload_hex"] == "22 F1 90"
    assert frame_rows[1]["payload_hex"] == "85 02"


def test_cli_client_rejects_non_client_service_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    uds = tmp_path / "response.csv"
    frames = tmp_path / "frames.csv"
    uds.write_text("service_id,did,payload_hex\n0x7F,,22 31\n", encoding="utf-8")

    assert (
        main(["client", "--transport", "j1939", "--input", str(uds), "--output", str(frames)])
        == 1
    )
    assert "not a supported UDS client request" in capsys.readouterr().err


def test_cli_server_j1939_generates_response_frames(tmp_path: Path) -> None:
    requests = tmp_path / "requests.csv"
    responses = tmp_path / "responses.csv"
    requests.write_text(
        "protocol,can_id,pgn,source_address,destination_address,payload_hex\n"
        "j1939,0x18DADAF9,0xDADA,0xF9,0xDA,22 F1 90\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "server",
                "--transport",
                "j1939",
                "--input",
                str(requests),
                "--output",
                str(responses),
                "--response-payload",
                "12 34",
            ]
        )
        == 0
    )

    response_rows = rows(responses)
    assert response_rows == [
        {
            "protocol": "j1939",
            "can_id": "0x18DAF9DA",
            "pgn": "0xDAF9",
            "source_address": "0xDA",
            "destination_address": "0xF9",
            "payload_hex": "62 F1 90 12 34",
        }
    ]


def test_cli_server_ethernet_generates_negative_response(tmp_path: Path) -> None:
    requests = tmp_path / "requests.csv"
    responses = tmp_path / "responses.csv"
    requests.write_text(
        "protocol,host,port,payload_hex\n"
        "ethernet,127.0.0.1,13400,62 F1 90 12 34\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "server",
                "--transport",
                "ethernet",
                "--input",
                str(requests),
                "--output",
                str(responses),
                "--host",
                "192.0.2.30",
                "--port",
                "13401",
                "--negative-response-code",
                "0x12",
            ]
        )
        == 0
    )

    response_rows = rows(responses)
    assert response_rows == [
        {
            "protocol": "ethernet",
            "host": "192.0.2.30",
            "port": "13401",
            "payload_hex": "7F 62 12",
        }
    ]


def test_cli_server_live_mode_calls_senders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    j1939_requests = tmp_path / "j1939.csv"
    ethernet_requests = tmp_path / "ethernet.csv"
    j1939_responses = tmp_path / "j1939_responses.csv"
    ethernet_responses = tmp_path / "ethernet_responses.csv"
    j1939_requests.write_text(
        "protocol,can_id,pgn,source_address,destination_address,payload_hex\n"
        "j1939,0x18DADAF9,0xDADA,0xF9,0xDA,22 F1 90\n",
        encoding="utf-8",
    )
    ethernet_requests.write_text(
        "protocol,host,port,payload_hex\n"
        "ethernet,127.0.0.1,13400,22 F1 90\n",
        encoding="utf-8",
    )
    sent: list[str] = []

    monkeypatch.setattr(
        "udsdiag.cli.send_socketcan_raw",
        lambda frame, interface: sent.append(interface),
    )
    monkeypatch.setattr("udsdiag.cli.send_ethernet_udp", lambda frame: sent.append(frame.host))

    assert (
        main(
            [
                "server",
                "--transport",
                "j1939",
                "--input",
                str(j1939_requests),
                "--output",
                str(j1939_responses),
                "--mode",
                "live",
                "--interface",
                "can2",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "server",
                "--transport",
                "ethernet",
                "--input",
                str(ethernet_requests),
                "--output",
                str(ethernet_responses),
                "--mode",
                "live",
                "--host",
                "192.0.2.40",
            ]
        )
        == 0
    )
    assert sent == ["can2", "192.0.2.40"]


def test_cli_server_rejects_invalid_negative_response_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests = tmp_path / "requests.csv"
    responses = tmp_path / "responses.csv"
    requests.write_text(
        "protocol,host,port,payload_hex\n"
        "ethernet,127.0.0.1,13400,22 F1 90\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "server",
                "--transport",
                "ethernet",
                "--input",
                str(requests),
                "--output",
                str(responses),
                "--negative-response-code",
                "0x100",
            ]
        )
        == 1
    )
    assert "negative_response_code out of range" in capsys.readouterr().err


def test_cli_serve_ethernet_runs_udp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_server(
        host: str,
        port: int,
        handler: Callable[[bytes], bytes],
        *,
        max_messages: int | None,
    ) -> int:
        captured["host"] = host
        captured["port"] = port
        captured["max_messages"] = max_messages
        captured["response"] = handler(b"\x22\xf1\x90")
        return 1

    monkeypatch.setattr("udsdiag.cli.serve_ethernet_udp", fake_server)

    assert (
        main(
            [
                "serve",
                "--transport",
                "ethernet",
                "--host",
                "127.0.0.1",
                "--port",
                "13400",
                "--response-payload",
                "12 34",
                "--max-messages",
                "1",
            ]
        )
        == 0
    )
    assert captured == {
        "host": "127.0.0.1",
        "port": 13400,
        "max_messages": 1,
        "response": b"\x62\xf1\x90\x12\x34",
    }


def test_cli_serve_ethernet_accepts_unlimited_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_server(
        host: str,
        port: int,
        handler: Callable[[bytes], bytes],
        *,
        max_messages: int | None,
    ) -> int:
        captured["max_messages"] = max_messages
        captured["response"] = handler(b"\x22\xf1\x90")
        return 1

    monkeypatch.setattr("udsdiag.cli.serve_ethernet_udp", fake_server)

    assert main(["serve", "--transport", "ethernet"]) == 0
    assert captured == {"max_messages": None, "response": b"\x62\xf1\x90"}


def test_cli_serve_rejects_j1939(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["serve", "--transport", "j1939"]) == 1
    assert "serve currently supports ethernet" in capsys.readouterr().err


def test_cli_serve_rejects_invalid_max_messages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["serve", "--transport", "ethernet", "--max-messages", "0"]) == 1
    assert "max_messages out of range" in capsys.readouterr().err


def test_cli_client_live_ethernet_captures_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uds = tmp_path / "uds.csv"
    responses = tmp_path / "responses.csv"
    uds.write_text("service_id,did,payload_hex\n0x22,0xF190,\n", encoding="utf-8")

    monkeypatch.setattr("udsdiag.cli.exchange_ethernet_udp", lambda frame, timeout: b"\x62\xf1\x90")

    assert (
        main(
            [
                "client",
                "--transport",
                "ethernet",
                "--input",
                str(uds),
                "--output",
                str(responses),
                "--mode",
                "live",
                "--timeout",
                "0.5",
            ]
        )
        == 0
    )
    assert rows(responses) == [
        {
            "protocol": "ethernet",
            "host": "127.0.0.1",
            "port": "13400",
            "payload_hex": "62 F1 90",
        }
    ]


def test_cli_client_live_ethernet_rejects_invalid_timeout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    uds = tmp_path / "uds.csv"
    output = tmp_path / "responses.csv"
    uds.write_text("service_id,did,payload_hex\n0x22,0xF190,\n", encoding="utf-8")

    assert (
        main(
            [
                "client",
                "--transport",
                "ethernet",
                "--input",
                str(uds),
                "--output",
                str(output),
                "--mode",
                "live",
                "--timeout",
                "0",
            ]
        )
        == 1
    )
    assert "timeout must be positive" in capsys.readouterr().err


def test_cli_client_live_ethernet_rejects_non_numeric_timeout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    uds = tmp_path / "uds.csv"
    output = tmp_path / "responses.csv"
    uds.write_text("service_id,did,payload_hex\n0x22,0xF190,\n", encoding="utf-8")

    assert (
        main(
            [
                "client",
                "--transport",
                "ethernet",
                "--input",
                str(uds),
                "--output",
                str(output),
                "--mode",
                "live",
                "--timeout",
                "soon",
            ]
        )
        == 1
    )
    assert "timeout must be a number" in capsys.readouterr().err


def test_cli_send_receive_ethernet(tmp_path: Path) -> None:
    uds = tmp_path / "uds.csv"
    frames = tmp_path / "frames.csv"
    decoded = tmp_path / "decoded.csv"
    write_uds(uds)

    assert (
        main(
            [
                "send",
                "--transport",
                "ethernet",
                "--input",
                str(uds),
                "--output",
                str(frames),
                "--host",
                "192.0.2.10",
                "--port",
                "13401",
            ]
        )
        == 0
    )
    assert rows(frames)[0]["host"] == "192.0.2.10"

    assert (
        main(
            [
                "receive",
                "--transport",
                "ethernet",
                "--input",
                str(frames),
                "--output",
                str(decoded),
            ]
        )
        == 0
    )
    assert rows(decoded)[0]["did"] == "0xF190"


def test_cli_live_mode_calls_senders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uds = tmp_path / "uds.csv"
    j1939_frames = tmp_path / "j1939.csv"
    ethernet_frames = tmp_path / "ethernet.csv"
    write_uds(uds)
    sent: list[str] = []

    def fake_exchange_socketcan(
        frame: object, interface: str, response_can_id: int, timeout: float
    ) -> bytes:
        sent.append(interface)
        return b"\x62\xf1\x90"

    monkeypatch.setattr("udsdiag.cli.exchange_socketcan", fake_exchange_socketcan)

    def exchange_response(frame: EthernetFrame, timeout: float) -> bytes:
        sent.append(frame.host)
        return b"\x62\xf1\x90"

    monkeypatch.setattr("udsdiag.cli.exchange_ethernet_udp", exchange_response)

    assert (
        main(
            [
                "send",
                "--transport",
                "j1939",
                "--input",
                str(uds),
                "--output",
                str(j1939_frames),
                "--mode",
                "live",
                "--interface",
                "can1",
                "--response-can-id",
                "0x7E8",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "send",
                "--transport",
                "ethernet",
                "--input",
                str(uds),
                "--output",
                str(ethernet_frames),
                "--mode",
                "live",
                "--host",
                "192.0.2.20",
            ]
        )
        == 0
    )
    assert sent == [
        "can1",
        "can1",
        "can1",
        "192.0.2.20",
        "192.0.2.20",
        "192.0.2.20",
    ]
    assert rows(ethernet_frames)[0]["payload_hex"] == "62 F1 90"


def test_cli_returns_error_for_invalid_csv(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    uds = tmp_path / "bad.csv"
    output = tmp_path / "out.csv"
    uds.write_text("service_id,did,payload_hex\n0x100,,\n", encoding="utf-8")

    assert (
        main(["send", "--transport", "j1939", "--input", str(uds), "--output", str(output)])
        == 1
    )
    assert "service_id out of range" in capsys.readouterr().err


def test_run_rejects_unknown_command() -> None:
    with pytest.raises(DiagnosticError, match="unknown command"):
        run(Namespace(command="other"))


def test_cli_client_live_doip_calls_exchange_doip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uds = tmp_path / "uds.csv"
    output = tmp_path / "out.csv"
    uds.write_text("service_id,did,payload_hex\n0x22,0xF190,\n", encoding="utf-8")
    called: list[tuple[int, int]] = []

    def fake_exchange_doip(
        frame: object, source_address: int, target_address: int, timeout: float
    ) -> bytes:
        called.append((source_address, target_address))
        return b"\x62\xf1\x90\xAB\xCD"

    monkeypatch.setattr("udsdiag.cli.exchange_doip", fake_exchange_doip)

    assert (
        main(
            [
                "client",
                "--transport", "ethernet",
                "--input", str(uds),
                "--output", str(output),
                "--mode", "live",
                "--doip",
                "--doip-source-address", "0x0E00",
                "--doip-target-address", "0x0001",
            ]
        )
        == 0
    )
    assert called == [(0x0E00, 0x0001)]
    assert rows(output)[0]["payload_hex"] == "62 F1 90 AB CD"


def test_cli_client_j1939_live_requires_response_can_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    uds = tmp_path / "uds.csv"
    output = tmp_path / "out.csv"
    uds.write_text("service_id,did,payload_hex\n0x22,0xF190,\n", encoding="utf-8")

    assert (
        main(
            [
                "client",
                "--transport", "j1939",
                "--input", str(uds),
                "--output", str(output),
                "--mode", "live",
                "--interface", "can0",
                # --response-can-id intentionally omitted
            ]
        )
        == 1
    )
    assert "--response-can-id is required" in capsys.readouterr().err