"""FFmpeg audio filter presets and ``-af`` chain construction.

The module is intentionally dependency-free (standard library only) so the
dashboard can import it without pulling in Discord, yt-dlp or ffmpeg.  The
strings returned by :func:`build_filter_chain` are ready to be placed after an
``-af`` flag; the flag itself is added by :mod:`src.voice_audio`.
"""

from __future__ import annotations

from collections.abc import Iterable

# Canonical preset keys.  The dashboard uses these keys verbatim, so keep the
# set stable and the descriptions user-facing.
FILTER_PRESETS: dict[str, dict] = {
    "bass": {
        "name": "Bass Boost",
        "description": "Adds depth and punch to low frequencies.",
    },
    "soft": {
        "name": "Soft",
        "description": "Rolls off harsh highs for a warmer, gentler sound.",
    },
    "lofi": {
        "name": "Lo-Fi",
        "description": "Narrows the frequency range for a vintage, muffled feel.",
    },
    "slowed reverb": {
        "name": "Slowed + Reverb",
        "description": "Slows the track down and adds a spacious echo.",
    },
    "reverb": {
        "name": "Reverb",
        "description": "Adds a short hall-style echo without changing tempo.",
    },
    "sped up": {
        "name": "Sped Up",
        "description": "Raises the pitch and tempo for a nightcore-style sound.",
    },
    "dolby": {
        "name": "Dolby",
        "description": "Widens the stereo image and lifts bass and treble.",
    },
    "8d": {
        "name": "8D Audio",
        "description": "Moves the sound around the listener in a slow orbit.",
    },
    "concert": {
        "name": "Concert",
        "description": "Adds a large-room echo with extra low-end weight.",
    },
    "instrumental": {
        "name": "Instrumental",
        "description": "Removes the centered vocal using stereo cancellation.",
    },
}

# Aliases are normalized (lowercase, spaces instead of ``-``/``_``) and map to
# one of the canonical keys above.
FILTER_ALIASES: dict[str, str] = {
    # bass
    "bass": "bass",
    "bb": "bass",
    "bassboost": "bass",
    "bass boost": "bass",
    # soft
    "soft": "soft",
    "warm": "soft",
    "mellow": "soft",
    "smooth": "soft",
    # lofi
    "lofi": "lofi",
    "lo fi": "lofi",
    "chill": "lofi",
    # slowed reverb
    "slowed": "slowed reverb",
    "slowed reverb": "slowed reverb",
    "slowed + reverb": "slowed reverb",
    # reverb
    "reverb": "reverb",
    "echo": "reverb",
    "hall": "reverb",
    # sped up
    "sped up": "sped up",
    "spedup": "sped up",
    "nightcore": "sped up",
    "fast": "sped up",
    # dolby
    "dolby": "dolby",
    "atmos": "dolby",
    "surround": "dolby",
    "spatial": "dolby",
    # 8d
    "8d": "8d",
    "orbit": "8d",
    "rotation": "8d",
    # concert
    "concert": "concert",
    "stadium": "concert",
    "arena": "concert",
    "live": "concert",
    # instrumental
    "instrumental": "instrumental",
    "karaoke": "instrumental",
    "vocaloff": "instrumental",
    "vocal off": "instrumental",
}

# Fixed order keeps the generated chain deterministic regardless of the input
# set/list ordering.
_FILTER_ORDER = (
    "bass",
    "soft",
    "lofi",
    "slowed reverb",
    "reverb",
    "sped up",
    "dolby",
    "8d",
    "concert",
    "instrumental",
)

_FILTER_CHAINS: dict[str, str] = {
    "soft": "lowpass=f=12000,equalizer=f=4000:t=q:w=1:g=-2",
    "lofi": "lowpass=f=2800,highpass=f=80,equalizer=f=200:t=q:w=1:g=2",
    "slowed reverb": (
        "asetrate=44100*0.88,aresample=44100,atempo=1.02,"
        "aecho=0.8:0.9:60|90:0.25|0.18"
    ),
    "reverb": "aecho=0.7:0.85:80|120:0.22|0.15",
    "sped up": "asetrate=44100*1.18,aresample=44100,atempo=1.0",
    "dolby": (
        "stereotools=mlev=0.9,equalizer=f=120:t=q:w=1:g=3,"
        "equalizer=f=8000:t=q:w=1:g=2"
    ),
    "8d": "apulsator=hz=0.2:mode=sine",
    "concert": (
        "aecho=0.8:0.88:120|200:0.25|0.18,"
        "equalizer=f=100:t=q:w=1:g=3"
    ),
    "instrumental": (
        "pan=stereo|c0=c0-c1|c1=c1-c0,"
        "equalizer=f=220:t=q:w=2:g=-4"
    ),
}


def _normalize(raw: str) -> str:
    """Lowercase and collapse separators so aliases compare consistently."""

    normalized = (
        raw.strip()
        .lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace("+", " ")
    )
    return " ".join(normalized.split())


def resolve_filter_name(raw: str) -> str | None:
    """Return the canonical preset key for ``raw``, or ``None`` if unknown."""

    if not isinstance(raw, str):
        return None
    key = _normalize(raw)
    if not key:
        return None
    canonical = FILTER_ALIASES.get(key)
    if canonical is not None:
        return canonical
    if key in FILTER_PRESETS:
        return key
    return None


def _bass_gains(bass_level: int) -> tuple[float, float, float]:
    """Map ``bass_level`` 1..999 to three clamped EQ gains (1..12 dB)."""

    try:
        level = int(bass_level)
    except (TypeError, ValueError):
        level = 10
    level = max(1, min(999, level))
    # Square-root curve: the low end of the slider is audible immediately while
    # the top end still reaches the 12 dB ceiling.
    gain = 1.0 + ((level - 1) / 998.0) ** 0.5 * 11.0
    return (
        max(1.0, min(12.0, gain)),
        max(1.0, min(12.0, gain * 0.65)),
        max(1.0, min(12.0, gain * 0.35)),
    )


def _bass_chain(bass_level: int) -> str:
    g1, g2, g3 = _bass_gains(bass_level)
    return (
        f"equalizer=f=60:t=q:w=1:g={g1:.1f},"
        f"equalizer=f=120:t=q:w=1:g={g2:.1f},"
        f"equalizer=f=250:t=q:w=1:g={g3:.1f}"
    )


def _clamp_volume(volume_pct: int) -> int:
    try:
        value = int(volume_pct)
    except (TypeError, ValueError):
        return 100
    return max(0, min(200, value))


def build_filter_chain(
    active: set[str] | list[str],
    bass_level: int = 10,
    volume_pct: int = 100,
) -> str | None:
    """Build an ffmpeg ``-af`` chain for the requested presets and volume.

    Unknown names are ignored.  When both ``"sped up"`` and
    ``"slowed reverb"`` are requested, ``"sped up"`` wins and
    ``"slowed reverb"`` is dropped (the two tempo changes are mutually
    exclusive).

    The returned string never includes the leading ``-af`` flag.  ``None`` is
    returned when there is nothing to apply (no known filters and volume at
    100%).
    """

    requested: set[str] = set()
    if isinstance(active, str):
        candidates: Iterable[object] = (active,)
    else:
        try:
            candidates = iter(active)
        except TypeError:
            candidates = ()

    for raw in candidates:
        if not isinstance(raw, str):
            continue
        name = resolve_filter_name(raw)
        if name is not None:
            requested.add(name)

    if "sped up" in requested:
        requested.discard("slowed reverb")

    parts: list[str] = []
    for name in _FILTER_ORDER:
        if name not in requested:
            continue
        if name == "bass":
            parts.append(_bass_chain(bass_level))
        else:
            parts.append(_FILTER_CHAINS[name])

    volume = _clamp_volume(volume_pct)
    if volume != 100:
        parts.append(f"volume={volume / 100:g}")
        if volume > 100:
            parts.append("alimiter=limit=0.95")

    if not parts:
        return None
    return ",".join(parts)
