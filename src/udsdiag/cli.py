from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from udsdiag.csvio import read_rows, write_rows
from udsdiag.live import send_ethernet_udp, send_socketcan_raw
from udsdiag.transport import (
    ETHERNET_DEFAULT_HOST,
    ETHERNET_DEFAULT_PORT,
    J1939_DEFAULT_DESTINATION,
    J1939_DEFAULT_SOURCE,
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

    for command in ("client", "send", "receive"):
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
        subparser.add_argument("--host", default=ETHERNET_DEFAULT_HOST)
        subparser.add_argument("--port", default=str(ETHERNET_DEFAULT_PORT))
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
            for j1939_frame in j1939_frames:
                send_socketcan_raw(j1939_frame, args.interface)
        write_rows(
            args.output,
            (j1939_to_row(j1939_frame) for j1939_frame in j1939_frames),
            J1939_FIELDS,
        )
        return 0

    port = parse_int(args.port, field="port", minimum=1, maximum=65535)
    ethernet_frames = [encode_ethernet(message, host=args.host, port=port) for message in messages]
    if args.mode == "live":
        for ethernet_frame in ethernet_frames:
            send_ethernet_udp(ethernet_frame)
    write_rows(
        args.output,
        (ethernet_to_row(ethernet_frame) for ethernet_frame in ethernet_frames),
        ETHERNET_FIELDS,
    )
    return 0


def receive_command(args: argparse.Namespace) -> int:
    input_rows = read_rows(args.input)
    if args.transport == "j1939":
        messages = [decode_j1939(j1939_from_row(row)) for row in input_rows]
    else:
        messages = [decode_ethernet(ethernet_from_row(row)) for row in input_rows]
    write_rows(args.output, (uds_to_row(message) for message in messages), UDS_FIELDS)
    return 0


def run(args: argparse.Namespace) -> int:
    if args.command in {"client", "send"}:
        return client_command(args)
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
