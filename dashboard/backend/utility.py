"""Utility actions for the local dashboard.

Weather and image generation do not need a Discord connection. Emoji copy and
server clone are delegated to ``BotAdapter.run_utility`` so the API can report
``bot_offline`` honestly until a live adapter is installed.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

import aiohttp

WMO_CODES = {
    0: "Clear sky ☀️",
    1: "Mainly clear 🌤️",
    2: "Partly cloudy ⛅",
    3: "Overcast ☁️",
    45: "Fog 🌫️",
    48: "Depositing rime fog 🌫️",
    51: "Light drizzle 🌦️",
    53: "Moderate drizzle 🌦️",
    55: "Dense drizzle 🌦️",
    56: "Light freezing drizzle 🌧️",
    57: "Dense freezing drizzle 🌧️",
    61: "Slight rain 🌧️",
    63: "Moderate rain 🌧️",
    65: "Heavy rain 🌧️",
    66: "Light freezing rain 🌧️",
    67: "Heavy freezing rain 🌧️",
    71: "Slight snow ❄️",
    73: "Moderate snow ❄️",
    75: "Heavy snow ❄️",
    77: "Snow grains ❄️",
    80: "Slight rain showers 🌦️",
    81: "Moderate rain showers 🌧️",
    82: "Violent rain showers ⛈️",
    85: "Slight snow showers 🌨️",
    86: "Heavy snow showers 🌨️",
    95: "Thunderstorm ⛈️",
    96: "Thunderstorm with slight hail ⛈️",
    99: "Thunderstorm with heavy hail ⛈️",
}

_COORDS_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$"
)


class UtilityError(Exception):
    """A user-facing utility failure with a stable error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def fetch_json(url: str, timeout: float = 10.0) -> tuple[int, Any]:
    """Fetch a JSON document. Kept separate so tests can replace it."""
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url) as response:
                try:
                    data = await response.json(content_type=None)
                except Exception:
                    data = None
                return response.status, data
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise UtilityError("upstream_error") from None


async def fetch_weather(location: str) -> dict[str, Any]:
    """Return current weather for a city name or ``lat,lon`` pair."""
    coords = _COORDS_RE.match(location)
    if coords:
        latitude = float(coords.group(1))
        longitude = float(coords.group(2))
        display = location.strip()
    else:
        status, data = await fetch_json(
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={quote(location)}&count=1&language=en"
        )
        if status != 200 or not isinstance(data, dict):
            raise UtilityError("upstream_error")

        results = data.get("results") or []
        if not results:
            raise UtilityError("location_not_found")

        first = results[0]
        latitude = first.get("latitude")
        longitude = first.get("longitude")
        if latitude is None or longitude is None:
            raise UtilityError("location_not_found")

        display = (
            ", ".join(
                part
                for part in (first.get("name"), first.get("country"))
                if part
            )
            or location.strip()
        )

    status, data = await fetch_json(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,apparent_temperature,"
        "relative_humidity_2m,weather_code,wind_speed_10m"
    )
    current = data.get("current") if isinstance(data, dict) else None
    if status != 200 or not isinstance(current, dict):
        raise UtilityError("upstream_error")

    weather_code = current.get("weather_code")
    return {
        "location": display,
        "latitude": latitude,
        "longitude": longitude,
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "weather_code": weather_code,
        "description": WMO_CODES.get(weather_code, "Unknown"),
    }


def image_result(prompt: str) -> dict[str, str]:
    """Build the keyless Pollinations image URL used by ``.genimg``."""
    return {
        "prompt": prompt,
        "url": f"https://image.pollinations.ai/prompt/{quote(prompt)}",
    }
