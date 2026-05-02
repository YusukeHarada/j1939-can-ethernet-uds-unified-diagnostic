from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    src_path = Path(__file__).resolve().parent / "src"
    sys.path.insert(0, str(src_path))

    from udsdiag.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
