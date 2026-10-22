"""Entry point for ``python -m wardogs_flight_eng``."""

import importlib


def run() -> None:
    """Delegate to the command-line interface module."""
    importlib.import_module("wardogs_flight_eng.cli").main()


if __name__ == "__main__":
    run()
