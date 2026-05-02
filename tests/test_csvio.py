from __future__ import annotations

from pathlib import Path

import pytest

from udsdiag.csvio import read_rows, write_rows
from udsdiag.uds import DiagnosticError


def test_read_and_write_rows(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"

    write_rows(path, [{"a": "1", "b": "2"}], ["a", "b"])

    assert read_rows(path) == [{"a": "1", "b": "2"}]


def test_read_rows_rejects_empty_csv(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("a,b\n", encoding="utf-8")

    with pytest.raises(DiagnosticError, match="CSV has no data rows"):
        read_rows(path)


def test_read_rows_rejects_extra_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2,3\n", encoding="utf-8")

    with pytest.raises(DiagnosticError, match="extra unnamed columns"):
        read_rows(path)


def test_read_rows_wraps_os_error(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError, match="failed to read CSV"):
        read_rows(tmp_path / "missing.csv")


def test_write_rows_wraps_errors(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError, match="failed to write CSV"):
        write_rows(tmp_path, [{"a": "1"}], ["a"])


def test_write_rows_rejects_extra_keys(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticError, match="failed to write CSV"):
        write_rows(tmp_path / "bad.csv", [{"a": "1", "b": "2"}], ["a"])
