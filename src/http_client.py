"""
Shared HTTP client cho Discord API — 1 ClientSession dùng chung toàn bot
+ tự retry khi bị rate limit 429 (theo Retry-After header).
"""

import asyncio
import logging
import random

import aiohttp

from .client_identity import discord_headers

logger = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None
_session_loop = None  # event loop mà session đang gắn vào
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3


async def get_session() -> aiohttp.ClientSession:
    """Lazy singleton session dùng chung — tạo lại khi event loop đổi (crash-restart)."""
    global _session, _session_loop
    loop = asyncio.get_running_loop()
    if _session is None or _session.closed or _session_loop is not loop:
        if _session is not None and not _session.closed:
            try:
                await _session.close()
            except Exception:
                pass
        _session = aiohttp.ClientSession()
        _session_loop = loop
    return _session


async def close_session():
    """Đóng shared session (gọi khi shutdown bot)."""
    global _session, _session_loop
    if _session and not _session.closed:
        await _session.close()
    _session = None
    _session_loop = None


async def api_request(method, url, token=None, json_body=None, timeout=DEFAULT_TIMEOUT,
                      session_identity=None):
    """
    Gửi request qua shared session, tự retry khi 429 theo Retry-After.
    Returns (status, data):
        - status: HTTP status code, None nếu lỗi mạng
        - data: dict/list parsed từ JSON body, None nếu không có/lỗi parse
    """
    session = await get_session()
    is_discord = url.startswith(
        ("https://discord.com/api/", "https://discordapp.com/api/")
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    if is_discord:
        headers.update(discord_headers(session_identity))
    if token:
        headers["Authorization"] = token
    if json_body is not None:
        headers["Content-Type"] = "application/json"

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                status = resp.status

                if status == 429 and attempt < MAX_RETRIES:
                    # Global rate limit: X-RateLimit-Global + retry_after (float, giây) trong body
                    is_global = resp.headers.get("X-RateLimit-Global", "").lower() == "true"
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        data = await resp.json()
                    except Exception:
                        data = None
                    if retry_after is None and isinstance(data, dict):
                        retry_after = data.get("retry_after")
                    try:
                        delay = float(retry_after) if retry_after is not None else 1.0
                    except (TypeError, ValueError):
                        delay = 1.0
                    max_delay = 120.0 if is_global else 30.0
                    delay = max(0.5, min(delay, max_delay))
                    logger.warning(
                        "HTTP 429 %s (%s) — retry sau %.1fs (lần %d/%d)",
                        url, "global" if is_global else "route", delay, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if status == 429:
                    # 429 lần cuối — đọc body 1 lần, không đọc lại
                    try:
                        data = await resp.json()
                    except Exception:
                        data = None
                    return 429, data

                if 500 <= status < 600 and attempt < MAX_RETRIES:
                    delay = 1 + attempt * 2 + random.uniform(0, 1)
                    logger.warning(
                        "HTTP %d %s — retry sau %.1fs (lần %d/%d)",
                        status, url, delay, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.content_type == "application/json":
                    try:
                        data = await resp.json()
                    except Exception:
                        data = None
                else:
                    data = None
                return status, data
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            # Lỗi mạng/timeout nhất thời — retry thay vì bỏ cuộc ngay
            if attempt < MAX_RETRIES:
                logger.warning(
                    "HTTP %s %s lỗi mạng (%s) — retry lần %d/%d",
                    method, url, type(e).__name__, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(1 + attempt)
                continue
            logger.error("HTTP %s %s lỗi mạng sau %d lần: %s", method, url, MAX_RETRIES + 1, e)
            return None, None
        except Exception as e:
            logger.error("HTTP %s %s lỗi: %s", method, url, e)
            return None, None

    return None, None


async def fetch_bytes(url, timeout=DEFAULT_TIMEOUT):
    """Tải nội dung binary (ảnh...) qua shared session. Retry 429/5xx. Trả về bytes hoặc None."""
    session = await get_session()
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.read()

                if resp.status == 429 and attempt < MAX_RETRIES:
                    is_global = resp.headers.get("X-RateLimit-Global", "").lower() == "true"
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        data = await resp.json()
                    except Exception:
                        data = None
                    if retry_after is None and isinstance(data, dict):
                        retry_after = data.get("retry_after")
                    try:
                        delay = float(retry_after) if retry_after is not None else 1.0
                    except (TypeError, ValueError):
                        delay = 1.0
                    max_delay = 120.0 if is_global else 30.0
                    delay = max(0.5, min(delay, max_delay))
                    logger.warning("fetch_bytes 429 %s (%s) — retry sau %.1fs (%d/%d)", url, "global" if is_global else "route", delay, attempt + 1, MAX_RETRIES)
                    await asyncio.sleep(delay)
                    continue

                if resp.status == 429:
                    # 429 lần cuối — trả None thay vì đọc body đã consumable
                    return None

                if 500 <= resp.status < 600 and attempt < MAX_RETRIES:
                    delay = 1 + attempt * 2 + random.uniform(0, 1)
                    logger.warning("fetch_bytes %d %s — retry sau %.1fs (%d/%d)", resp.status, url, delay, attempt + 1, MAX_RETRIES)
                    await asyncio.sleep(delay)
                    continue

                logger.error("Fetch %s lỗi HTTP %s", url, resp.status)
                return None
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            if attempt < MAX_RETRIES:
                logger.warning("fetch_bytes %s lỗi mạng (%s) — retry %d/%d", url, type(e).__name__, attempt + 1, MAX_RETRIES)
                await asyncio.sleep(1 + attempt)
                continue
            logger.error("Fetch %s lỗi mạng sau %d lần: %s", url, MAX_RETRIES + 1, e)
            return None
        except Exception as e:
            logger.error("Fetch %s lỗi: %s", url, e)
            return None
    return None
