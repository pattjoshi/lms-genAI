"""Slow down password guessing: after AUTH_MAX_FAILED_LOGINS wrong passwords for one email (or many
from one IP address), further tries are refused for AUTH_LOCKOUT_MINUTES.

Kept in memory: enough for one backend process. With several processes you'd keep these counters in
Redis or Postgres so every process sees the same count.
"""

import time
from collections import defaultdict, deque

from app.config import get_settings

IP_FACTOR = 4  # one IP may fail this many times more than one email (a shared office or classroom network)

_failures: dict[str, deque[float]] = defaultdict(deque)


def _recent(key: str, window: float) -> deque[float]:
    times = _failures[key]
    cutoff = time.monotonic() - window
    while times and times[0] < cutoff:
        times.popleft()
    return times


def retry_after(email: str, ip: str | None) -> int:
    """Seconds until another try is allowed for this email / IP, or 0 if allowed now."""
    s = get_settings()
    window = s.auth_lockout_minutes * 60
    checks = [(f"email:{email}", s.auth_max_failed_logins)]
    if ip:
        checks.append((f"ip:{ip}", s.auth_max_failed_logins * IP_FACTOR))
    waits = []
    for key, limit in checks:
        times = _recent(key, window)
        if len(times) >= limit:
            waits.append(int(times[0] + window - time.monotonic()) + 1)
    return max(waits, default=0)


def record_failure(email: str, ip: str | None) -> None:
    now = time.monotonic()
    _failures[f"email:{email}"].append(now)
    if ip:
        _failures[f"ip:{ip}"].append(now)


def clear(email: str) -> None:
    _failures.pop(f"email:{email}", None)


def reset_all() -> None:
    """Tests only."""
    _failures.clear()
