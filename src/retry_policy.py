"""Retry policy for the Discord login loop.

Authentication failures must never be retried. Repeated login attempts with a
bad/revoked token look like account compromise to Discord and can trigger a
forced password reset, so those failures stop the process immediately.

Only transient/network failures are retried, a bounded number of times, with
exponential backoff plus jitter.
"""

import random

import discord

# Gateway close codes that mean "this token/session will never work".
# 4003  not authenticated
# 4004  authentication failed
# 4006  session no longer valid
# 4010  invalid shard
# 4011  sharding required
# 4012  invalid API version
# 4013  invalid intents
# 4014  disallowed intents
AUTH_CLOSE_CODES = {4003, 4004, 4006, 4010, 4011, 4012, 4013, 4014}

# How many consecutive network failures to retry before giving up.
MAX_NETWORK_RETRIES = 3

AUTH = "auth"
NETWORK = "network"


def classify_failure(exc):
    """Classify an exception raised while running the client.

    Returns ``"auth"`` when the token can never work (``discord.LoginFailure``
    or an exception carrying an auth gateway close code), otherwise
    ``"network"``. The close code is read duck-typed so callers/tests can pass
    any object with a ``code`` attribute.
    """
    if isinstance(exc, discord.LoginFailure):
        return AUTH

    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in AUTH_CLOSE_CODES:
        return AUTH

    return NETWORK


def retry_delay(attempt, base=15.0, cap=120.0, jitter=0.25):
    """Exponential backoff for a zero-based retry ``attempt``.

    ``min(cap, base * 2 ** attempt)`` seconds, multiplied by
    ``1 + random.uniform(-jitter, jitter)`` so retries do not synchronize.
    """
    delay = min(cap, base * (2 ** attempt))
    return delay * (1 + random.uniform(-jitter, jitter))
