import unittest
from unittest.mock import patch, MagicMock
from app.sync.auto_cleanup import AutoCleanupRunner


class TestAutoCleanup(unittest.TestCase):
    def test_runner_disabled_does_not_start_thread(self):
        runner = AutoCleanupRunner()
        with patch("app.sync.auto_cleanup.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(auto_cleanup_enabled=False)
            runner.start()
            self.assertIsNone(runner._thread)
            runner.stop()

    def test_runner_enabled_starts_and_stops_thread(self):
        runner = AutoCleanupRunner()
        with patch("app.sync.auto_cleanup.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                auto_cleanup_enabled=True,
                auto_cleanup_interval_minutes=60,
                auto_cleanup_grace_hours=24,
            )
            runner.start()
            self.assertIsNotNone(runner._thread)
            self.assertTrue(runner._thread.is_alive())
            runner.stop(timeout=1.0)
            self.assertFalse(runner._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
