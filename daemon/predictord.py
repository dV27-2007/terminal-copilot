from __future__ import annotations

from .main import main as cli_main


def main() -> int:
    return cli_main(["daemon"])


if __name__ == "__main__":
    raise SystemExit(main())
