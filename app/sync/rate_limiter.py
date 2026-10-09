import random
import time
from typing import Optional


class RateLimiter:
    """Enforces conservative request delays, jitter, and throttling pauses for traffic smoothing."""

    def __init__(
        self,
        base_delay_seconds: float = 1.0,
        jitter_ratio: float = 0.2,
    ) -> None:
        self.base_delay_seconds = max(0.0, base_delay_seconds)
        self.jitter_ratio = max(0.0, min(1.0, jitter_ratio))
        self._last_request_time: float = 0.0
        self._paused_until: float = 0.0

    @property
    def is_paused(self) -> bool:
        return time.time() < self._paused_until

    @property
    def remaining_pause(self) -> float:
        remaining = self._paused_until - time.time()
        return max(0.0, remaining)

    def pause(self, seconds: float = 60.0) -> None:
        self._paused_until = max(self._paused_until, time.time() + max(0.0, seconds))

    def resume(self) -> None:
        self._paused_until = 0.0

    def wait(self, custom_delay: Optional[float] = None) -> float:
        """Sleeps if needed to enforce rate limit or throttling. Returns time waited in seconds."""
        now = time.time()
        total_waited = 0.0

        # Handle upstream throttling pause first
        if now < self._paused_until:
            pause_time = self._paused_until - now
            time.sleep(pause_time)
            total_waited += pause_time
            now = time.time()

        # Compute next target delay with jitter
        delay = self.base_delay_seconds if custom_delay is None else max(0.0, custom_delay)
        if delay > 0 and self.jitter_ratio > 0:
            jitter = random.uniform(-self.jitter_ratio, self.jitter_ratio)
            delay = delay * (1.0 + jitter)

        # ponytail: in-process time.sleep limiter with jitter; ceiling is single-worker instance, upgrade to distributed token bucket / Redis limiter if multi-process worker cluster needed
        elapsed = now - self._last_request_time
        if elapsed < delay:
            sleep_time = delay - elapsed
            time.sleep(sleep_time)
            total_waited += sleep_time

        self._last_request_time = time.time()
        return total_waited
