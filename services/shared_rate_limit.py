import hashlib
import hmac
import os
import secrets
import time
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError


class SharedRateLimitUnavailable(RuntimeError):
    pass


_CHECK_LIMIT_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry_after = math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
    return {0, retry_after}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


@lru_cache(maxsize=4)
def _redis_client(redis_url: str) -> Redis:
    return Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def check_shared_rate_limit(
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        raise SharedRateLimitUnavailable("REDIS_URL is required for production OTP rate limiting.")

    secret = os.getenv("WT_AUTH_SECRET", "").strip()
    if len(secret) < 32:
        raise SharedRateLimitUnavailable("WT_AUTH_SECRET must be configured for shared OTP rate limiting.")
    identity = hmac.new(
        secret.encode(),
        f"{scope}:{subject}".encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        client = _redis_client(redis_url)
    except (RedisError, ValueError) as exc:
        raise SharedRateLimitUnavailable("Redis OTP rate limiting is unavailable.") from exc
    now_ms = int(time.time() * 1000)
    try:
        result = client.eval(
            _CHECK_LIMIT_SCRIPT,
            1,
            f"wt:otp-rate:{identity}",
            now_ms,
            window_seconds * 1000,
            limit,
            secrets.token_urlsafe(12),
        )
    except RedisError as exc:
        raise SharedRateLimitUnavailable("Redis OTP rate limiting is unavailable.") from exc
    return bool(int(result[0])), int(result[1])
