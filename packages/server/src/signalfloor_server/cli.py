"""Command line entry point: `signalfloor-server serve` and `signalfloor-server migrate`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from signalfloor_server import migrate
from signalfloor_server.app import create_app
from signalfloor_server.config import Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signalfloor-server")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    commands.add_parser("migrate", help="bring the database schema up to date")

    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "migrate":
        migrate.upgrade(settings.database_url)
        print("database schema is up to date")
    else:
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0
