"""Command-line entry point."""

import argparse
from collections.abc import Sequence

from paper_pile import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-pile",
        description="Local markdown notes with built-in local AI.",
    )
    parser.add_argument("vault", nargs="?", help="vault directory (default: last vault)")
    parser.add_argument("--serve", action="store_true", help="web mode on 127.0.0.1")
    parser.add_argument("--port", type=int, default=8080, help="port for --serve")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
