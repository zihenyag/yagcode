from __future__ import annotations

import sys
import tomllib

from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    root = Path(args[0]) if args else Path.cwd()
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    print(data["project"]["version"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
