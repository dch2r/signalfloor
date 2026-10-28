"""Command line entry point for the server, the worker and maintenance tasks."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections.abc import Sequence
from datetime import timedelta

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker

from signalfloor_server import jobs, migrate, retention
from signalfloor_server.app import create_app, create_engine
from signalfloor_server.config import Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signalfloor-server")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    commands.add_parser("migrate", help="bring the database schema up to date")

    worker = commands.add_parser("worker", help="run background jobs until stopped")
    worker.add_argument(
        "--poll-interval", type=float, default=1.0, help="seconds to wait when idle (default 1)"
    )

    prune = commands.add_parser("prune-spans", help="delete old trace spans")
    prune.add_argument(
        "--older-than-days", type=float, default=30, help="keep this many days (default 30)"
    )

    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "migrate":
        migrate.upgrade(settings.database_url)
        print("database schema is up to date")
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        asyncio.run(_work(settings, args.poll_interval))
    elif args.command == "prune-spans":
        deleted = asyncio.run(_prune(settings, timedelta(days=args.older_than_days)))
        print(f"deleted {deleted} spans older than {args.older_than_days:g} days")
    else:
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0


async def _work(settings: Settings, poll_interval: float) -> None:
    # Kubernetes sends SIGTERM before it kills a pod. Finish the current job, then exit.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    engine = create_engine(settings)
    try:
        await jobs.work(async_sessionmaker(engine), stop, poll_interval=poll_interval)
    finally:
        await engine.dispose()


async def _prune(settings: Settings, older_than: timedelta) -> int:
    engine = create_engine(settings)
    try:
        async with async_sessionmaker(engine)() as session:
            return await retention.prune_spans(session, older_than)
    finally:
        await engine.dispose()
