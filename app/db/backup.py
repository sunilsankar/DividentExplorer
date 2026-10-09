"""Backup and restore the SQLite database."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Sequence


def _check_integrity(connection: sqlite3.Connection, path: Path) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        detail = "no result" if result is None else str(result[0])
        raise ValueError(f"{path} failed integrity check: {detail}")


def _replace_with_backup(source: Path, destination: Path) -> None:
    source = source.expanduser()
    destination = destination.expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")
    if source.resolve() == destination.resolve():
        raise ValueError("SQLite source and destination must be different files")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)

    try:
        # ponytail: sqlite3.Connection.backup() copies live SQLite databases safely; ceiling is single-file local filesystem, upgrade to litestream or S3 streaming replica if distributed disaster recovery needed
        with sqlite3.connect(source) as source_connection:
            _check_integrity(source_connection, source)
            with sqlite3.connect(temporary) as destination_connection:
                source_connection.backup(destination_connection)
                _check_integrity(destination_connection, temporary)
        os.replace(temporary, destination)
        for suffix in ("-wal", "-shm"):
            Path(f"{destination}{suffix}").unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(database: str | Path, output: str | Path) -> None:
    """Create an atomic, integrity-checked backup of a SQLite database."""

    _replace_with_backup(Path(database), Path(output))


def restore_database(backup: str | Path, database: str | Path) -> None:
    """Restore an integrity-checked backup into a SQLite database path."""

    _replace_with_backup(Path(backup), Path(database))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="create a database backup")
    backup.add_argument("--database", required=True, type=Path)
    backup.add_argument("--output", required=True, type=Path)

    restore = commands.add_parser("restore", help="restore a database backup")
    restore.add_argument("--database", required=True, type=Path)
    restore.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            backup_database(args.database, args.output)
        else:
            restore_database(args.input, args.database)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
