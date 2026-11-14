"""Pure-Python ranking helpers for yt-dlp music search results.

Ported from GhoSty Music Selfbot V6 ``core/search.py`` and adapted to the
flat entry dictionaries returned by ``yt-dlp`` (``extract_flat``).  The
module performs no network I/O and deliberately does not import ``yt_dlp``
or any third-party package, so it is safe on a minimal Arm64 container.

Only :class:`SearchCache` guards shared state, using a ``threading.Lock`` so
the engine can read it from a worker thread.  Everything else is synchronous
and side-effect free at import time.
"""

from __future__ import annotations

import difflib
import re
import threading
import time
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Reference constants (values kept compatible with GhoSty V6)
# ---------------------------------------------------------------------------

MODIFIER_SYNONYMS: dict[str, list[str]] = {
    "slowed": [
        "slowed",
        "slow",
        "slowe",
        "slowed+reverb",
        "slowed & reverb",
        "slowed and reverb",
        "chopped",
    ],
    "reverb": ["reverb", "reverbe", "reverbed"],
    "sped up": [
        "sped up",
        "spedup",
        "speed up",
        "speedup",
        "accelerated",
        "fast",
    ],
    "nightcore": ["nightcore", "nightcor", "nc"],
    "daycore": ["daycore"],
    "remix": ["remix", "remx", "flip", "bootleg", "vip", "vip mix"],
    "edit": ["edit", "audio edit"],
    "bass boosted": ["bass boosted", "bassboost", "bassboosted", "bass"],
    "instrumental": [
        "instrumental",
        "inst",
        "karaoke",
        "no vocals",
        "backing track",
    ],
    "acoustic": ["acoustic", "acoustc", "unplugged", "piano"],
    "clean": ["clean", "clean version", "radio edit"],
    "explicit": ["explicit", "dirty"],
    "live": ["live", "concert", "performance", "tour"],
    "cover": ["cover", "tribute"],
    "loop": [
        "1 hour",
        "1hr",
        "10 hour",
        "10hr",
        "loop",
        "extended",
        "extended mix",
        "compilation",
        "full album",
    ],
}

TYPO_CORRECTIONS: dict[str, str] = {
    "slowe": "slowed",
    "reverbe": "reverb",
    "remx": "remix",
    "spedup": "sped up",
    "speedup": "sped up",
    "nightcor": "nightcore",
    "inst": "instrumental",
    "acoustc": "acoustic",
    "bassboost": "bass boosted",
    "bassboosted": "bass boosted",
    "offical": "official",
    "offcial": "official",
}

JUNK_KEYWORDS = [
    "review",
    "reaction",
    "reacting",
    "how to play",
    "tutorial",
    "lesson",
    "parody",
    "unboxing",
    "teaser",
    "guitar lesson",
    "piano tutorial",
]

TRUSTED_CHANNEL_TAGS = [
    "topic",
    "vevo",
    "official",
    "records",
    "music",
    "audiomack",
    "label",
    "recordings",
]

HIGH_QUALITY_TITLE_TAGS = [
    "official audio",
    "official music video",
    "original mix",
    "provided to youtube",
    "audio visualizer",
]

URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(value: str) -> str:
    """Lowercase, strip punctuation, apply typo fixes and collapse spaces."""

    tokens = _WORD_RE.findall(str(value or "").lower())
    corrected = [TYPO_CORRECTIONS.get(token, token) for token in tokens]
    return _WHITESPACE_RE.sub(" ", " ".join(corrected)).strip()


_INFLECTION_SUFFIX = r"(?:s|es|ed|d|ing|er|ers|est)?"


def _contains_synonym(
    text: str, synonym: str, *, allow_inflections: bool = False
) -> bool:
    """Return True when ``synonym`` appears as a whole word/phrase in ``text``.

    Query detection keeps strict word boundaries.  Title scoring may allow
    common inflections (``remixed``, ``covered``, ``looped``) so a modifier
    is still recognized without matching unrelated words such as ``alive``.
    """

    suffix = _INFLECTION_SUFFIX if allow_inflections else ""
    pattern = r"\b" + re.escape(synonym) + suffix + r"\b"
    return re.search(pattern, text) is not None


def normalize_query(query: str) -> tuple[str, set[str]]:
    """Normalize a search query and return ``(text, detected_modifiers)``.

    Punctuation is replaced with spaces, the text is lowercased, typo
    corrections are applied per token, and modifiers are detected with
    word-boundary regexes so ``"live"`` does not match ``"alive"``.
    """

    normalized = _normalize_text(query)
    modifiers = {
        name
        for name, synonyms in MODIFIER_SYNONYMS.items()
        if any(_contains_synonym(normalized, synonym) for synonym in synonyms)
    }
    return normalized, modifiers


def is_url(query: str) -> bool:
    """Return True when ``query`` is a single http(s) URL."""

    return bool(URL_PATTERN.match(str(query or "").strip()))


def compute_string_similarity(a: str, b: str) -> float:
    """Score two strings in the range 0.0-1.0.

    Exact matches return 1.0.  Substring matches return
    ``0.85 + 0.15 * (shorter / longer)``.  Otherwise the better of token
    overlap (scaled by 0.9) and :class:`difflib.SequenceMatcher` wins.
    """

    s1 = _PUNCTUATION_RE.sub(" ", str(a or "").lower()).strip()
    s2 = _PUNCTUATION_RE.sub(" ", str(b or "").lower()).strip()

    if not s1 or not s2:
        return 0.0

    if s1 == s2:
        return 1.0

    if s1 in s2 or s2 in s1:
        shorter = min(len(s1), len(s2))
        longer = max(len(s1), len(s2))
        return 0.85 + 0.15 * (shorter / longer)

    t1 = set(s1.split())
    t2 = set(s2.split())
    if not t1 or not t2:
        return 0.0

    token_score = len(t1.intersection(t2)) / max(len(t1), 1)
    sequence_score = difflib.SequenceMatcher(None, s1, s2).ratio()

    return max(token_score * 0.9, sequence_score)


# ---------------------------------------------------------------------------
# yt-dlp flat-entry scoring
# ---------------------------------------------------------------------------


def _entry_title(entry: dict) -> str:
    return str(entry.get("title") or "")


def _entry_author(entry: dict) -> str:
    # yt-dlp flat entries expose the channel as either uploader or channel.
    return str(entry.get("uploader") or entry.get("channel") or "")


def _entry_duration(entry: dict) -> float | None:
    """Return duration in seconds, or None when unknown/invalid."""

    value = entry.get("duration")
    if value is None:
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if duration < 0:
        return None
    return duration


def _entry_is_live(entry: dict) -> bool:
    if entry.get("is_live"):
        return True
    return entry.get("live_status") == "is_live"


def score_entry(entry: dict, query: str, modifiers: set[str]) -> float:
    """Score one yt-dlp flat entry against a query.

    The weights mirror the reference implementation: similarity up to 45,
    author overlap up to 20, modifier match/mismatch +25/-22, junk -35,
    duration heuristics, trusted channel +8 and high-quality title +7.
    The result is clamped at zero.
    """

    title = _entry_title(entry)
    author = _entry_author(entry)
    lower_title = title.lower()
    lower_author = author.lower()
    normalized_query = _normalize_text(query)
    requested = set(modifiers or ())
    is_live = _entry_is_live(entry)

    score = 0.0

    # Similarity against the title alone and against "author - title".
    full_candidate = f"{lower_author} - {lower_title}"
    title_similarity = compute_string_similarity(normalized_query, lower_title)
    full_similarity = compute_string_similarity(normalized_query, full_candidate)
    score += max(title_similarity, full_similarity) * 45.0

    # Author overlap: each overlapping token is worth 10, capped at 20.
    query_tokens = set(_PUNCTUATION_RE.sub(" ", normalized_query).split())
    author_tokens = set(_PUNCTUATION_RE.sub(" ", lower_author).split())
    author_overlap = query_tokens.intersection(author_tokens)
    if author_overlap:
        score += min(len(author_overlap) * 10.0, 20.0)

    # Modifiers present in the title (normalized so "Sped-Up" is recognized).
    modifier_title = _normalize_text(title)
    present_modifiers = {
        name
        for name, synonyms in MODIFIER_SYNONYMS.items()
        if any(
            _contains_synonym(modifier_title, synonym, allow_inflections=True)
            for synonym in synonyms
        )
    }
    if is_live:
        present_modifiers.add("live")

    for name in MODIFIER_SYNONYMS:
        requested_here = name in requested
        present_here = name in present_modifiers

        if requested_here and present_here:
            score += 25.0
        elif requested_here and not present_here:
            score -= 22.0
        elif present_here and not requested_here:
            if name in ("live", "cover"):
                score -= 30.0
            elif name in ("slowed", "nightcore", "bass boosted"):
                score -= 15.0

    # Junk results are penalized once, even if several junk tags match.
    if any(
        junk in lower_title
        for junk in JUNK_KEYWORDS
        if junk not in normalized_query
    ):
        score -= 35.0

    # Duration heuristics.  Unknown durations and live streams are neutral.
    if not is_live:
        duration = _entry_duration(entry)
        if duration is not None:
            if duration < 45.0:
                if "loop" not in requested:
                    score -= 35.0
            elif duration > 900.0:
                if "loop" not in requested:
                    score -= 30.0
            elif 90.0 <= duration <= 420.0:
                score += 10.0

    if any(tag in lower_author for tag in TRUSTED_CHANNEL_TAGS):
        score += 8.0
    if any(tag in lower_title for tag in HIGH_QUALITY_TITLE_TAGS):
        score += 7.0

    return max(score, 0.0)


def rank_entries(
    entries: list[dict], query: str, modifiers: set[str]
) -> list[dict]:
    """Return ``entries`` sorted by descending score, preserving ties."""

    scored = [(score_entry(entry, query, modifiers), entry) for entry in entries]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored]


# ---------------------------------------------------------------------------
# Async TTL/FIFO cache
# ---------------------------------------------------------------------------


class SearchCache:
    """Small thread-safe cache with TTL expiry and FIFO eviction.

    ``clock`` can be injected for deterministic tests.  Entries are stored
    in dict insertion order; when a *new* key would exceed ``maxsize`` the
    oldest key is evicted first.  Both synchronous (``get_sync``/``put_sync``)
    and asynchronous (``get``/``put``) accessors are provided so the engine can
    use the cache from a worker thread while async callers keep working.
    """

    def __init__(
        self,
        maxsize: int = 300,
        ttl: float = 1800.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._clock = clock
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_sync(self, key: str) -> Any:
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None

            stored_at, value = item
            if self._clock() - stored_at > self.ttl:
                del self._cache[key]
                return None
            return value

    def put_sync(self, key: str, value: Any) -> None:
        with self._lock:
            if self.maxsize <= 0:
                return

            if key not in self._cache and len(self._cache) >= self.maxsize:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            self._cache[key] = (self._clock(), value)

    def clear_sync(self) -> None:
        with self._lock:
            self._cache.clear()

    async def get(self, key: str) -> Any:
        return self.get_sync(key)

    async def put(self, key: str, value: Any) -> None:
        self.put_sync(key, value)

    async def clear(self) -> None:
        self.clear_sync()


GLOBAL_SEARCH_CACHE = SearchCache()
