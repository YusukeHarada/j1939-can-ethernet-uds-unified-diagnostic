from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from udsdiag.uds import DiagnosticError


def read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise DiagnosticError(f"failed to read CSV: {path}") from exc
    if not rows:
        raise DiagnosticError(f"CSV has no data rows: {path}")
    if rows[0] and None not in rows[0]:
        return rows
    raise DiagnosticError(f"CSV contains extra unnamed columns: {path}")


def write_rows(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    row_list = list(rows)
    try:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
            writer.writeheader()
            writer.writerows(row_list)
    except (OSError, ValueError) as exc:
        raise DiagnosticError(f"failed to write CSV: {path}") from exc
