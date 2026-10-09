import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.backup import backup_database, main, restore_database


class DatabaseBackupTests(unittest.TestCase):
    def test_backup_copies_wal_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.db"
            backup = root / "backups" / "source.db"

            connection = sqlite3.connect(database)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE values_table (value TEXT)")
                connection.execute("INSERT INTO values_table VALUES ('kept')")
                connection.commit()
                backup_database(database, backup)
            finally:
                connection.close()

            with sqlite3.connect(backup) as connection:
                value = connection.execute(
                    "SELECT value FROM values_table"
                ).fetchone()[0]
            self.assertEqual(value, "kept")

    def test_restore_replaces_database_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup.db"
            database = root / "database.db"

            with sqlite3.connect(backup) as connection:
                connection.execute("CREATE TABLE values_table (value TEXT)")
                connection.execute("INSERT INTO values_table VALUES ('restored')")
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE values_table (value TEXT)")
                connection.execute("INSERT INTO values_table VALUES ('old')")

            restore_database(backup, database)

            with sqlite3.connect(database) as connection:
                value = connection.execute(
                    "SELECT value FROM values_table"
                ).fetchone()[0]
            self.assertEqual(value, "restored")

    def test_invalid_sqlite_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.db"
            invalid.write_text("not a SQLite database")

            with self.assertRaises(sqlite3.DatabaseError):
                backup_database(invalid, root / "backup.db")

    def test_cli_returns_nonzero_for_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = main(
                [
                    "backup",
                    "--database",
                    str(root / "missing.db"),
                    "--output",
                    str(root / "backup.db"),
                ]
            )
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
