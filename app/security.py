import os
import secrets
import time
from collections import defaultdict, deque
from hashlib import sha256
from threading import Lock

from fastapi import Header, HTTPException, Response, status


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


class APIKeyRateLimiter:
    """Authenticate API keys and apply an in-process sliding-window limit."""

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def reset(self) -> None:
        """Clear request history (primarily useful for isolated test runs)."""
        with self._lock:
            self._requests.clear()

    def __call__(
        self,
        response: Response,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> str:
        configured_key = os.getenv("API_KEY", "").strip()
        if not configured_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API access is not configured.",
            )
        if x_api_key is None or not secrets.compare_digest(x_api_key, configured_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A valid API key is required.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        limit = _positive_int("API_RATE_LIMIT", 60)
        window = _positive_int("API_RATE_WINDOW_SECONDS", 60)
        now = time.monotonic()
        with self._lock:
            # Keep only a non-reversible key identifier in rate-limit state.
            key_id = sha256(x_api_key.encode("utf-8")).hexdigest()
            requests = self._requests[key_id]
            cutoff = now - window
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                retry_after = max(1, int(window - (now - requests[0])) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="API rate limit exceeded.",
                    headers={"Retry-After": str(retry_after)},
                )
            requests.append(now)
            remaining = limit - len(requests)

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return x_api_key


require_api_key = APIKeyRateLimiter()
