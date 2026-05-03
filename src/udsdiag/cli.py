from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from udsdiag.csvio import read_rows, write_rows
from udsdiag.live import (
    exchange_doip,
    exchange_ethernet_udp,
    exchange_socketcan,
    send_ethernet_udp,
    send_socketcan_raw,
    serve_ethernet_udp,
)
from udsdiag.transport import (
    ETHERNET_DEFAULT_HOST,
    ETHERNET_DEFAULT_PORT,
    J1939_DEFAULT_DESTINATION,
    J1939_DEFAULT_SOURCE,
    EthernetFrame,
    J1939Frame,
    decode_ethernet,
    decode_j1939,
    encode_ethernet,
    encode_j1939,
    ethernet_from_row,
    ethernet_to_row,
    j1939_from_row,
    j1939_to_row,
)
from udsdiag.uds import (
    DiagnosticError,
    UdsMessage,
    build_server_response,
    parse_hex_bytes,
    parse_int,
    uds_from_row,
    uds_to_row,
)

J1939_FIELDS = [
    "protocol",
    "can_id",
    "pgn",
    "source_address",
    "destination_address",
    "payload_hex",
]
ETHERNET_FIELDS = ["protocol", "host", "port", "payload_hex"]
UDS_FIELDS = ["service_id", "did", "payload_hex", "status"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="udsdiag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("client", "server", "send", "receive"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--transport", choices=["j1939", "ethernet"], required=True)
        subparser.add_argument("--input", type=Path, required=True)
        subparser.add_argument("--output", type=Path, required=True)
        subparser.add_argument("--mode", choices=["simulate", "live"], default="simulate")
        subparser.add_argument("--source-address", default=f"0x{J1939_DEFAULT_SOURCE:02X}")
        subparser.add_argument(
            "--destination-address",
            default=f"0x{J1939_DEFAULT_DESTINATION:02X}",
        )
        subparser.add_argument("--interface", default="can0")
        subparser.add_argument("--response-can-id", default="")
        subparser.add_argument("--host", default=ETHERNET_DEFAULT_HOST)
        subparser.add_argument("--port", default=str(ETHERNET_DEFAULT_PORT))
        subparser.add_argument("--doip", action="store_true",
                               help="Use DoIP (ISO 13400-2) TCP instead of UDP")
        subparser.add_argument("--doip-source-address", default="0x0E00")
        subparser.add_argument("--doip-target-address", default="0x0001")
        subparser.add_argument("--response-payload", default="")
        subparser.add_argument("--negative-response-code", default="0x11")
        subparser.add_argument("--timeout", default="1.0")

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--transport", choices=["j1939", "ethernet"], required=True)
    serve_parser.add_argument("--host", default=ETHERNET_DEFAULT_HOST)
    serve_parser.add_argument("--port", default=str(ETHERNET_DEFAULT_PORT))
    serve_parser.add_argument("--response-payload", default="")
    serve_parser.add_argument("--negative-response-code", default="0x11")
    serve_parser.add_argument("--max-messages", default="")
    return parser


def read_client_requests(path: Path) -> list[UdsMessage]:
    messages = [uds_from_row(row) for row in read_rows(path)]
    for message in messages:
        message.validate_client_request()
    return messages


def client_command(args: argparse.Namespace) -> int:
    if args.command == "client":
        messages = read_client_requests(args.input)
    else:
        messages = [uds_from_row(row) for row in read_rows(args.input)]
    if args.transport == "j1939":
        source = parse_int(
            args.source_address,
            field="source_address",
            minimum=0,
            maximum=0xFF,
        )
        dest = parse_int(
            args.destination_address,
            field="destination_address",
            minimum=0,
            maximum=0xFF,
        )
        j1939_frames = [
            encode_j1939(message, source_address=source, destination_address=dest)
            for message in messages
        ]
        if args.mode == "live":
            resp_can_id_str = getattr(args, "response_can_id", "")
            if not resp_can_id_str.strip():
                raise DiagnosticError(
                    "--response-can-id is required for J1939 live mode"
                )
            resp_can_id = parse_int(
                resp_can_id_str,
                field="response_can_id",
                minimum=0,
                maximum=0x1FFFFFFF,
            )
            timeout = parse_timeout(args.timeout)
            j1939_response_frames: list[J1939Frame] = []
            for j1939_frame in j1939_frames:
                resp_payload = exchange_socketcan(
                    j1939_frame, args.interface, resp_can_id, timeout
                )
                j1939_response_frames.append(
                    encode_j1939(
                        UdsMessage.from_payload(resp_payload),
                        source_address=dest,
                        destination_address=source,
                    )
                )
            write_rows(
                args.output,
                (j1939_to_row(f) for f in j1939_response_frames),
                J1939_FIELDS,
            )
            return 0
        write_rows(
            args.output,
            (j1939_to_row(j1939_frame) for j1939_frame in j1939_frames),
            J1939_FIELDS,
        )
        return 0

    port = parse_int(args.port, field="port", minimum=1, maximum=65535)
    ethernet_frames = [encode_ethernet(message, host=args.host, port=port) for message in messages]
    output_frames: list[EthernetFrame] = list(ethernet_frames)
    if args.mode == "live":
        timeout = parse_timeout(args.timeout)
        response_frames: list[EthernetFrame] = []
        for ethernet_frame in ethernet_frames:
            if getattr(args, "doip", False):
                src_la = parse_int(
                    args.doip_source_address,
                    field="doip_source_address",
                    minimum=0,
                    maximum=0xFFFF,
                )
                tgt_la = parse_int(
                    args.doip_target_address,
                    field="doip_target_address",
                    minimum=0,
                    maximum=0xFFFF,
                )
                response_payload = exchange_doip(
                    ethernet_frame, src_la, tgt_la, timeout
                )
            else:
                response_payload = exchange_ethernet_udp(ethernet_frame, timeout)
            response_frames.append(
                encode_ethernet(
                    UdsMessage.from_payload(response_payload),
                    host=args.host,
                    port=port,
                )
            )
        output_frames = response_frames
    write_rows(
        args.output,
        (ethernet_to_row(ethernet_frame) for ethernet_frame in output_frames),
        ETHERNET_FIELDS,
    )
    return 0


def parse_timeout(text: str) -> float:
    try:
        timeout = float(text)
    except ValueError as exc:
        raise DiagnosticError(f"timeout must be a number: {text}") from exc
    if timeout <= 0:
        raise DiagnosticError(f"timeout must be positive: {text}")
    return timeout


def parse_optional_count(text: str) -> int | None:
    if not text.strip():
        return None
    return parse_int(text, field="max_messages", minimum=1, maximum=1_000_000)


def receive_command(args: argparse.Namespace) -> int:
    input_rows = read_rows(args.input)
    if args.transport == "j1939":
        messages = [decode_j1939(j1939_from_row(row)) for row in input_rows]
    else:
        messages = [decode_ethernet(ethernet_from_row(row)) for row in input_rows]
    write_rows(args.output, (uds_to_row(message) for message in messages), UDS_FIELDS)
    return 0


def serve_command(args: argparse.Namespace) -> int:
    if args.transport != "ethernet":
        raise DiagnosticError("serve currently supports ethernet transport only")
    port = parse_int(args.port, field="port", minimum=1, maximum=65535)
    response_payload = parse_hex_bytes(args.response_payload)
    negative_response_code = parse_int(
        args.negative_response_code,
        field="negative_response_code",
        minimum=0,
        maximum=0xFF,
    )

    def handle_request(payload: bytes) -> bytes:
        request = UdsMessage.from_payload(payload)
        response = build_server_response(
            request,
            response_payload=response_payload,
            negative_response_code=negative_response_code,
        )
        return response.to_payload()

    serve_ethernet_udp(
        args.host,
        port,
        handle_request,
        max_messages=parse_optional_count(args.max_messages),
    )
    return 0


def server_command(args: argparse.Namespace) -> int:
    response_payload = parse_hex_bytes(args.response_payload)
    negative_response_code = parse_int(
        args.negative_response_code,
        field="negative_response_code",
        minimum=0,
        maximum=0xFF,
    )
    input_rows = read_rows(args.input)
    if args.transport == "j1939":
        j1939_request_frames = [j1939_from_row(row) for row in input_rows]
        j1939_response_frames = []
        for request_frame in j1939_request_frames:
            request = decode_j1939(request_frame)
            response = build_server_response(
                request,
                response_payload=response_payload,
                negative_response_code=negative_response_code,
            )
            j1939_response_frames.append(
                encode_j1939(
                    response,
                    source_address=request_frame.destination_address,
                    destination_address=request_frame.source_address,
                )
            )
        if args.mode == "live":
            for response_frame in j1939_response_frames:
                send_socketcan_raw(response_frame, args.interface)
        write_rows(
            args.output,
            (j1939_to_row(response_frame) for response_frame in j1939_response_frames),
            J1939_FIELDS,
        )
        return 0

    ethernet_request_frames = [ethernet_from_row(row) for row in input_rows]
    port = parse_int(args.port, field="port", minimum=1, maximum=65535)
    ethernet_response_frames = []
    for ethernet_request_frame in ethernet_request_frames:
        request = decode_ethernet(ethernet_request_frame)
        response = build_server_response(
            request,
            response_payload=response_payload,
            negative_response_code=negative_response_code,
        )
        ethernet_response_frames.append(encode_ethernet(response, host=args.host, port=port))
    if args.mode == "live":
        for ethernet_response_frame in ethernet_response_frames:
            send_ethernet_udp(ethernet_response_frame)
    write_rows(
        args.output,
        (ethernet_to_row(response_frame) for response_frame in ethernet_response_frames),
        ETHERNET_FIELDS,
    )
    return 0


def run(args: argparse.Namespace) -> int:
    if args.command in {"client", "send"}:
        return client_command(args)
    if args.command == "server":
        return server_command(args)
    if args.command == "serve":
        return serve_command(args)
    if args.command == "receive":
        return receive_command(args)
    raise DiagnosticError(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except DiagnosticError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1