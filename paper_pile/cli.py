"""Command-line entry point."""

import argparse
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from paper_pile import __version__
from paper_pile.core.session import load_last_vault, save_last_vault
from paper_pile.core.vault import VaultError, ensure_vault_dir, resolve_vault_path

DEFAULT_PORT = 8080


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-pile",
        description="Local markdown notes with built-in local AI.",
    )
    parser.add_argument("vault", nargs="?", help="vault directory (default: last vault)")
    parser.add_argument("--serve", action="store_true", help="web mode on 127.0.0.1 (needs token)")
    parser.add_argument("--port", type=int, help=f"port for --serve (default {DEFAULT_PORT})")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _prompt_for_vault() -> Path:
    """First run with no last vault: ask in the terminal."""
    if not sys.stdin.isatty():
        raise VaultError("no vault given and none remembered; run: paper-pile <folder>")
    return resolve_vault_path(input("Vault folder: ").strip())


def pick_vault(arg: str | None) -> Path:
    """Vault from the CLI argument, else the last one used, else ask."""
    if arg is not None:
        return resolve_vault_path(arg)
    return load_last_vault() or _prompt_for_vault()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port is not None and not args.serve:
        parser.error("--port only makes sense with --serve")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        vault = pick_vault(args.vault)
    except VaultError as exc:
        parser.error(str(exc))
    ensure_vault_dir(vault)
    save_last_vault(vault)

    from paper_pile.gui import app  # imported late: keeps --help fast and core UI-free

    if args.serve:
        port = args.port or DEFAULT_PORT
        token = secrets.token_urlsafe(16)
        print(f"paper-pile serving {vault}\n  open: http://127.0.0.1:{port}/?token={token}")
        app.run_serve(vault, port, token)
    else:
        app.run_native(vault)
    return 0
