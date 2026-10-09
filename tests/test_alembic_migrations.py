import os
import tempfile
import unittest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


class AlembicMigrationsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_migration.db")
        self.alembic_cfg = Config("alembic.ini")
        self.alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upgrade_and_downgrade(self):
        # 1. Upgrade to head
        command.upgrade(self.alembic_cfg, "head")

        engine = create_engine(f"sqlite:///{self.db_path}")
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        engine.dispose()

        expected_tables = {
            "alembic_version",
            "exchanges",
            "companies",
            "dividend_events",
            "dividend_metrics",
            "price_history",
            "financial_metrics",
            "company_relationships",
            "sync_jobs",
            "sync_runs",
            "worker_status",
            "sync_state",
            "data_changes",
        }
        self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

        # 2. Downgrade to base
        command.downgrade(self.alembic_cfg, "base")

        engine = create_engine(f"sqlite:///{self.db_path}")
        inspector = inspect(engine)
        remaining_tables = set(inspector.get_table_names())
        engine.dispose()

        self.assertNotIn("companies", remaining_tables)
        self.assertNotIn("exchanges", remaining_tables)
        self.assertNotIn("sync_jobs", remaining_tables)


if __name__ == "__main__":
    unittest.main()
