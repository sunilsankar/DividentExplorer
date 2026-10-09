import time
import unittest

from app.sync.rate_limiter import RateLimiter


class TestRateLimiter(unittest.TestCase):
    def test_basic_wait(self):
        limiter = RateLimiter(base_delay_seconds=0.01, jitter_ratio=0.0)
        waited = limiter.wait()
        # First call has elapsed > 0.01 since _last_request_time is 0
        self.assertEqual(waited, 0.0)

        # Immediate second call must wait approximately 0.01s
        start = time.time()
        waited2 = limiter.wait()
        duration = time.time() - start
        self.assertGreaterEqual(duration, 0.008)

    def test_pause_and_resume(self):
        limiter = RateLimiter(base_delay_seconds=0.0, jitter_ratio=0.0)
        self.assertFalse(limiter.is_paused)
        self.assertEqual(limiter.remaining_pause, 0.0)

        limiter.pause(seconds=5.0)
        self.assertTrue(limiter.is_paused)
        self.assertGreater(limiter.remaining_pause, 2.0)

        limiter.resume()
        self.assertFalse(limiter.is_paused)
        self.assertEqual(limiter.remaining_pause, 0.0)


if __name__ == "__main__":
    unittest.main()
