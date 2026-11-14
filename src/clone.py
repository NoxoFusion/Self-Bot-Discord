"""
Clone Module
Xử lý clone server Discord — logger chuẩn, retry khi 429, map roles/categories theo ID
(tránh gán nhầm khi trùng tên; hierarchy tạo cao→thấp cho đúng thứ tự nguồn).

Thứ tự xóa an toàn: channels → categories → roles (roles cuối vì channel overwrites cần role).
Thứ tự tạo: roles → categories → channels (đảo ngược thứ tự xóa).
Rollback: backup state trước khi xóa, restore nếu clone fail giữa chừng.
"""

import discord
import asyncio
import logging
import random
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ==================== PACING ====================
# Wiping and rebuilding a server in minutes looks like account takeover to
# Discord and can trigger forced password resets. Pace every clone operation
# and pause in batches so a large clone looks like normal admin activity.

CLONE_MIN_DELAY = 3.0
CLONE_MAX_DELAY = 8.0
CLONE_BATCH_SIZE = 10
CLONE_BATCH_PAUSE_MIN = 20.0
CLONE_BATCH_PAUSE_MAX = 40.0
CLONE_MAX_ITEMS = 1000


def item_delay() -> float:
    """Random delay between individual clone operations."""
    return random.uniform(CLONE_MIN_DELAY, CLONE_MAX_DELAY)


def batch_pause() -> float:
    """Longer pause after each batch of clone operations."""
    return random.uniform(CLONE_BATCH_PAUSE_MIN, CLONE_BATCH_PAUSE_MAX)


async def _pace(counter: int) -> None:
    """Sleep after one clone item, adding a batch pause every Nth item."""
    await asyncio.sleep(item_delay())
    if counter % CLONE_BATCH_SIZE == 0:
        await asyncio.sleep(batch_pause())


# ==================== SOURCE SNAPSHOT ====================
# The guild cache can be partial (no channels/emojis, roles only for @everyone).
# These lightweight objects let the clone code use REST data (or freshly fetched
# discord objects) without requiring a fully populated guild cache.

@dataclass
class _SnapshotRole:
    id: int
    name: str
    permissions: discord.Permissions
    colour: discord.Colour
    hoist: bool = False
    mentionable: bool = False
    position: int = 0


@dataclass
class _SnapshotCategory:
    id: int
    name: str
    position: int = 0
    overwrites: dict = field(default_factory=dict)
    type: discord.ChannelType = discord.ChannelType.category


@dataclass
class _SnapshotChannel:
    id: int
    name: str
    type: discord.ChannelType
    position: int = 0
    category_id: int | None = None
    topic: str | None = None
    slowmode_delay: int = 0
    nsfw: bool = False
    bitrate: int = 64000
    user_limit: int = 0
    overwrites: dict = field(default_factory=dict)


@dataclass
class _SnapshotEmoji:
    id: int
    name: str
    url: str
    animated: bool = False

    async def read(self) -> bytes:
        from .http_client import fetch_bytes

        data = await fetch_bytes(self.url)
        if data is None:
            raise RuntimeError(f"Could not download emoji {self.name}")
        return data


def _channel_type(channel):
    """Return a ``discord.ChannelType`` for a guild channel or snapshot channel."""
    raw = getattr(channel, "type", None)
    if isinstance(raw, discord.ChannelType):
        return raw
    try:
        return discord.ChannelType(int(raw))
    except (TypeError, ValueError):
        return None


class SourceSnapshot:
    """Source data usable by the clone helpers in place of a cached guild."""

    def __init__(
        self,
        roles=None,
        categories=None,
        channels=None,
        emojis=None,
        *,
        name: str = "",
        guild_id=None,
    ):
        self.roles = list(roles or [])
        self.categories = list(categories or [])
        self._channels = list(channels or [])
        self.emojis = list(emojis or [])
        self.name = name
        self.id = guild_id

    @classmethod
    def from_parts(cls, roles=None, channels=None, emojis=None, *, name="", guild_id=None):
        """Build a snapshot from discord objects (e.g. ``fetch_channels()``)."""
        channels = list(channels or [])
        categories = [
            c for c in channels if _channel_type(c) == discord.ChannelType.category
        ]
        regular = [
            c for c in channels if _channel_type(c) != discord.ChannelType.category
        ]
        return cls(
            roles=roles,
            categories=categories,
            channels=regular,
            emojis=emojis,
            name=name,
            guild_id=guild_id,
        )

    @property
    def text_channels(self):
        return [
            c
            for c in self._channels
            if _channel_type(c) in (discord.ChannelType.text, discord.ChannelType.news)
        ]

    @property
    def voice_channels(self):
        return [
            c
            for c in self._channels
            if _channel_type(c)
            in (discord.ChannelType.voice, discord.ChannelType.stage_voice)
        ]

    @property
    def regular_channels(self):
        return list(self._channels)

    @property
    def channels(self):
        return list(self.categories) + list(self._channels)

    def __getitem__(self, key):
        """Allow dict-style reads for callers that build plain snapshot dicts."""
        if key == "guild_id":
            return self.id
        if key == "channels":
            return self.regular_channels
        return getattr(self, key)


def _coerce_source_snapshot(source_snapshot):
    """Accept either a ``SourceSnapshot`` or a plain snapshot dict."""
    if source_snapshot is None or isinstance(source_snapshot, SourceSnapshot):
        return source_snapshot
    if isinstance(source_snapshot, dict):
        return SourceSnapshot(
            roles=source_snapshot.get("roles"),
            categories=source_snapshot.get("categories"),
            channels=source_snapshot.get("channels"),
            emojis=source_snapshot.get("emojis"),
            name=source_snapshot.get("name", ""),
            guild_id=source_snapshot.get("id") or source_snapshot.get("guild_id"),
        )
    return source_snapshot


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_overwrites(raw_overwrites):
    """Parse REST permission_overwrites into {role_id: PermissionOverwrite}."""
    result = {}
    for raw in raw_overwrites or []:
        if not isinstance(raw, dict):
            continue
        # type 0 = role, 1 = member. The clone code maps roles by ID.
        if _as_int(raw.get("type"), 0) != 0:
            continue
        role_id = _as_int(raw.get("id"))
        if role_id is None:
            continue
        allow = discord.Permissions(_as_int(raw.get("allow"), 0) or 0)
        deny = discord.Permissions(_as_int(raw.get("deny"), 0) or 0)
        result[role_id] = discord.PermissionOverwrite.from_pair(allow, deny)
    return result


def build_source_snapshot(guild_payload, channel_payloads) -> SourceSnapshot | None:
    """Build a ``SourceSnapshot`` from raw Discord REST payloads.

    ``guild_payload`` is ``GET /guilds/{id}`` (roles + emojis) and
    ``channel_payloads`` is ``GET /guilds/{id}/channels``.
    """
    if not isinstance(guild_payload, dict):
        return None

    guild_id = _as_int(guild_payload.get("id"))
    roles = []
    for raw in guild_payload.get("roles") or []:
        if not isinstance(raw, dict):
            continue
        role_id = _as_int(raw.get("id"))
        if role_id is None:
            continue
        if role_id == guild_id or raw.get("name") == "@everyone":
            continue
        roles.append(
            _SnapshotRole(
                id=role_id,
                name=str(raw.get("name") or "role"),
                permissions=discord.Permissions(_as_int(raw.get("permissions"), 0) or 0),
                colour=discord.Colour(_as_int(raw.get("color"), 0) or 0),
                hoist=bool(raw.get("hoist")),
                mentionable=bool(raw.get("mentionable")),
                position=_as_int(raw.get("position"), 0) or 0,
            )
        )
    roles.sort(key=lambda role: role.position)

    emojis = []
    for raw in guild_payload.get("emojis") or []:
        if not isinstance(raw, dict):
            continue
        emoji_id = _as_int(raw.get("id"))
        if emoji_id is None:
            continue
        animated = bool(raw.get("animated"))
        extension = "gif" if animated else "png"
        emojis.append(
            _SnapshotEmoji(
                id=emoji_id,
                name=str(raw.get("name") or "emoji"),
                url=f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}",
                animated=animated,
            )
        )

    categories = []
    channels = []
    for raw in channel_payloads or []:
        if not isinstance(raw, dict):
            continue
        channel_id = _as_int(raw.get("id"))
        channel_type = _as_int(raw.get("type"))
        if channel_id is None or channel_type is None:
            continue
        name = str(raw.get("name") or "")
        position = _as_int(raw.get("position"), 0) or 0
        overwrites = _parse_overwrites(raw.get("permission_overwrites"))

        if channel_type == 4:
            categories.append(
                _SnapshotCategory(
                    id=channel_id,
                    name=name,
                    position=position,
                    overwrites=overwrites,
                )
            )
        elif channel_type in (0, 5):
            channels.append(
                _SnapshotChannel(
                    id=channel_id,
                    name=name,
                    type=discord.ChannelType.text
                    if channel_type == 0
                    else discord.ChannelType.news,
                    position=position,
                    category_id=_as_int(raw.get("parent_id")),
                    topic=raw.get("topic"),
                    slowmode_delay=_as_int(raw.get("rate_limit_per_user"), 0) or 0,
                    nsfw=bool(raw.get("nsfw")),
                    overwrites=overwrites,
                )
            )
        elif channel_type in (2, 13):
            channels.append(
                _SnapshotChannel(
                    id=channel_id,
                    name=name,
                    type=discord.ChannelType.voice
                    if channel_type == 2
                    else discord.ChannelType.stage_voice,
                    position=position,
                    category_id=_as_int(raw.get("parent_id")),
                    bitrate=_as_int(raw.get("bitrate"), 64000) or 64000,
                    user_limit=_as_int(raw.get("user_limit"), 0) or 0,
                    overwrites=overwrites,
                )
            )
        else:
            logger.debug("Skipping unsupported source channel type %s (%s)", channel_type, name)

    return SourceSnapshot(
        roles=roles,
        categories=categories,
        channels=channels,
        emojis=emojis,
        name=str(guild_payload.get("name") or ""),
        guild_id=guild_id,
    )


def _source_roles(source):
    return [
        role
        for role in getattr(source, "roles", []) or []
        if getattr(role, "name", "") != "@everyone"
    ]


def _source_categories(source):
    return list(getattr(source, "categories", []) or [])


def _source_text_channels(source):
    return list(getattr(source, "text_channels", []) or [])


def _source_voice_channels(source):
    return list(getattr(source, "voice_channels", []) or [])


def _source_channels(source):
    return _source_text_channels(source) + _source_voice_channels(source)


def _source_all_channels(source):
    """All non-category channels, including types the clone code cannot create.

    Used for the expected total so a source with only unsupported channel types
    cannot silently report success after deleting the target channels.
    """
    return [
        channel
        for channel in getattr(source, "channels", []) or []
        if _channel_type(channel) != discord.ChannelType.category
    ]


def _source_emojis(source):
    return list(getattr(source, "emojis", []) or [])


def _emit_progress(callback, step, done, total):
    if callback is None:
        return
    try:
        callback(step, done, total)
    except Exception as exc:
        logger.warning("Clone progress callback failed: %s", exc)


def _format_rollback(report):
    report = report or {}
    restored = report.get("restored", {})
    expected = report.get("expected", {})
    actual = report.get("actual", {})
    parts = []
    for key in ("roles", "categories", "channels", "emojis"):
        part = f"{key} {restored.get(key, 0)}/{expected.get(key, 0)}"
        if actual.get(key) is not None:
            part += f" (now {actual[key]})"
        parts.append(part)
    note = "rollback restored " + ", ".join(parts)
    failures = report.get("failures") or []
    if failures:
        note += f"; {len(failures)} restore failure(s)"
    return note


async def _safe_call(coro_factory):
    """Gọi API với retry khi bị 429 — đọc Retry-After header properly."""
    for attempt in range(3):
        try:
            return await coro_factory()
        except discord.HTTPException as e:
            if e.status == 429 and attempt < 2:
                retry_after = 2.0
                # Đọc Retry-After từ response nếu có
                if hasattr(e, 'response') and e.response is not None:
                    ra = e.response.headers.get('Retry-After')
                    if ra:
                        try:
                            retry_after = float(ra)
                        except (TypeError, ValueError):
                            retry_after = 2.0
                logger.warning(f"429 rate limit — retry sau {retry_after:.1f}s (lần {attempt + 1}/3)")
                await asyncio.sleep(retry_after)
                continue
            raise
    return None


def _has_permission(guild: discord.Guild, perm_name: str) -> bool:
    """Check bot permission trong guild. Trả False nếu bot không có trong guild."""
    me = getattr(guild, "me", None)
    if me is None:
        logger.error(
            "Bot không có trong guild '%s' (id=%s)",
            getattr(guild, "name", "?"),
            getattr(guild, "id", "?"),
        )
        return False
    return getattr(me.guild_permissions, perm_name, False)


def _missing_permissions(guild, perm_names):
    """Return the required permission names the bot lacks in ``guild``."""
    me = getattr(guild, "me", None)
    permissions = getattr(me, "guild_permissions", None) if me is not None else None
    missing = []
    for name in perm_names:
        if permissions is None or not getattr(permissions, name, False):
            missing.append(name)
    return missing


class CloneHandler:
    """Class xử lý clone server."""

    @staticmethod
    async def guild_edit(guild_to: discord.Guild, guild_from: discord.Guild):
        """Clone thông tin server (name, icon)."""
        if not _has_permission(guild_to, 'manage_guild'):
            return False

        try:
            await guild_to.edit(name=guild_from.name)
            logger.info(f"Đã đổi tên server thành: {guild_from.name}")

            if guild_from.icon:
                try:
                    icon_bytes = await guild_from.icon.read()
                    await guild_to.edit(icon=icon_bytes)
                    logger.info("Đã clone icon server")
                except Exception as e:
                    logger.warning(f"Không thể clone icon: {e}")

            return True

        except discord.Forbidden:
            logger.error(f"Thiếu quyền edit server {guild_to.name}")
            return False
        except Exception as e:
            logger.error(f"Lỗi edit server: {e}")
            return False

    # ==================== DELETE ====================

    @staticmethod
    async def roles_delete(guild_to: discord.Guild) -> int:
        """Xóa tất cả roles (trừ @everyone). Trả về số role đã xóa."""
        if not _has_permission(guild_to, 'manage_roles'):
            return 0

        deleted = 0
        counter = 0
        # Copy list vì guild_to.roles thay đổi khi xóa
        for role in list(guild_to.roles):
            if role.name == "@everyone":
                continue
            try:
                await _safe_call(role.delete)
                deleted += 1
                counter += 1
                await _pace(counter)
            except discord.Forbidden:
                logger.warning(f"Không thể xóa role: {role.name}")
            except Exception as e:
                logger.warning(f"Lỗi xóa role {role.name}: {e}")

        logger.info(f"Đã xóa {deleted} roles")
        return deleted

    @staticmethod
    async def channels_delete(guild_to: discord.Guild) -> int:
        """Xóa tất cả channels (text + voice). KHÔNG xóa categories riêng — để Discord tự dọn.
        Trả về số channel đã xóa."""
        if not _has_permission(guild_to, 'manage_channels'):
            return 0

        deleted = 0
        counter = 0
        # Copy list vì guild_to.channels thay đổi khi xóa
        for channel in list(guild_to.channels):
            # guild.channels chứa cả CategoryChannel — bỏ qua, để categories_delete xử lý
            if isinstance(channel, discord.CategoryChannel):
                continue
            try:
                await _safe_call(channel.delete)
                deleted += 1
                counter += 1
                await _pace(counter)
            except discord.Forbidden:
                logger.warning(f"Không thể xóa channel: {channel.name}")
            except Exception as e:
                logger.warning(f"Lỗi xóa channel {channel.name}: {e}")

        logger.info(f"Đã xóa {deleted} channels")
        return deleted

    @staticmethod
    async def categories_delete(guild_to: discord.Guild) -> int:
        """Xóa tất cả categories còn lại sau khi channels đã bị xóa."""
        if not _has_permission(guild_to, 'manage_channels'):
            return 0

        deleted = 0
        counter = 0
        for category in list(guild_to.categories):
            try:
                await _safe_call(category.delete)
                deleted += 1
                counter += 1
                await _pace(counter)
            except discord.Forbidden:
                logger.warning(f"Không thể xóa category: {category.name}")
            except Exception as e:
                logger.warning(f"Lỗi xóa category {category.name}: {e}")

        logger.info(f"Đã xóa {deleted} categories")
        return deleted

    # ==================== BACKUP / RESTORE ====================

    @staticmethod
    def backup_guild_state(guild: discord.Guild) -> dict:
        """Lưu trạng thái server để rollback nếu clone fail."""
        return {
            "name": guild.name,
            "icon": guild.icon,
            "roles": [
                {
                    "id": r.id,
                    "name": r.name, "permissions": r.permissions,
                    "colour": r.colour, "hoist": r.hoist, "mentionable": r.mentionable,
                }
                for r in guild.roles if r.name != "@everyone"
            ],
            "categories": [
                {"name": c.name, "position": c.position,
                 "overwrites": {str(k.id): v for k, v in c.overwrites.items() if isinstance(k, discord.Role)}}
                for c in guild.categories
            ],
            "channels": [
                {
                    "name": ch.name, "type": ch.type,
                    "topic": getattr(ch, 'topic', None),
                    "slowmode_delay": getattr(ch, 'slowmode_delay', 0),
                    "nsfw": getattr(ch, 'nsfw', False),
                    "bitrate": getattr(ch, 'bitrate', 64000),
                    "user_limit": getattr(ch, 'user_limit', 0),
                    "category_name": ch.category.name if ch.category else None,
                    "position": ch.position,
                    "overwrites": {str(k.id): v for k, v in ch.overwrites.items() if isinstance(k, discord.Role)},
                }
                for ch in guild.channels
                if not isinstance(ch, discord.CategoryChannel)
            ],
        }

    @staticmethod
    async def backup_emojis(guild: discord.Guild) -> list[dict]:
        """Lưu emoji hiện có của server đích để rollback nếu clone fail."""
        backup = []
        for emoji in list(guild.emojis):
            try:
                backup.append({"name": emoji.name, "image": await emoji.read()})
            except Exception as e:
                logger.warning(
                    "Không thể đọc emoji %s: %s", getattr(emoji, "name", "?"), e
                )
        return backup

    @staticmethod
    async def restore_guild_state(guild: discord.Guild, backup: dict) -> dict:
        """Khôi phục server từ backup (rollback khi clone fail).

        Returns a report with expected/restored/actual counts and any failures so
        callers can surface an incomplete rollback instead of only logging it.
        """
        expected = {
            "roles": len(backup.get("roles", [])),
            "categories": len(backup.get("categories", [])),
            "channels": len(backup.get("channels", [])),
            "emojis": len(backup.get("emojis", [])),
        }
        restored = {"roles": 0, "categories": 0, "channels": 0, "emojis": 0}
        failures = []

        # Restore tên + icon
        try:
            await guild.edit(name=backup["name"])
        except Exception as e:
            logger.warning("Restore name failed: %s", e)
            failures.append(f"name: {e}")
        if backup.get("icon"):
            try:
                icon_bytes = await backup["icon"].read()
                await guild.edit(icon=icon_bytes)
            except Exception as e:
                logger.warning("Restore icon failed: %s", e)
                failures.append(f"icon: {e}")

        # Restore roles — map theo ID gốc để khôi phục overwrites chính xác
        role_id_map = {}
        counter = 0
        for r_data in backup.get("roles", []):
            try:
                created = await _safe_call(lambda r=r_data: guild.create_role(
                    name=r["name"], permissions=r["permissions"],
                    colour=r["colour"], hoist=r["hoist"], mentionable=r["mentionable"],
                ))
                if created is not None:
                    role_id_map[r_data["id"]] = created
                    restored["roles"] += 1
                else:
                    failures.append(f"role {r_data.get('name')}: no result")
            except Exception as e:
                logger.warning("Restore role %s failed: %s", r_data.get("name"), e)
                failures.append(f"role {r_data.get('name')}: {e}")
            counter += 1
            await _pace(counter)

        # Restore categories
        cat_map = {}
        for c_data in backup.get("categories", []):
            try:
                overwrites = CloneHandler._map_backup_overwrites(c_data.get("overwrites"), role_id_map)
                new_cat = await _safe_call(lambda c=c_data, o=overwrites: guild.create_category(
                    name=c["name"], overwrites=o,
                ))
                if new_cat is not None:
                    cat_map[c_data["name"]] = new_cat
                    restored["categories"] += 1
                else:
                    failures.append(f"category {c_data.get('name')}: no result")
            except Exception as e:
                logger.warning("Restore category %s failed: %s", c_data.get("name"), e)
                failures.append(f"category {c_data.get('name')}: {e}")
            counter += 1
            await _pace(counter)

        # Restore channels
        for ch_data in backup.get("channels", []):
            try:
                category = cat_map.get(ch_data.get("category_name"))
                overwrites = CloneHandler._map_backup_overwrites(ch_data.get("overwrites"), role_id_map)

                created = None
                if ch_data["type"] in (
                    discord.ChannelType.text,
                    discord.ChannelType.news,
                    discord.ChannelType.private,
                ):
                    created = await _safe_call(lambda c=ch_data, cat=category: guild.create_text_channel(
                        name=c["name"], overwrites=overwrites,
                        position=c["position"], topic=c.get("topic"),
                        slowmode_delay=c.get("slowmode_delay", 0),
                        nsfw=c.get("nsfw", False), category=cat,
                    ))
                elif ch_data["type"] in (
                    discord.ChannelType.voice,
                    discord.ChannelType.stage_voice,
                ):
                    created = await _safe_call(lambda c=ch_data, cat=category: guild.create_voice_channel(
                        name=c["name"], overwrites=overwrites,
                        position=c["position"], bitrate=min(c.get("bitrate", 64000), guild.bitrate_limit),
                        user_limit=c.get("user_limit", 0), category=cat,
                    ))
                else:
                    failures.append(
                        f"channel {ch_data.get('name')}: unsupported type {ch_data['type']}"
                    )
                    continue

                if created is not None:
                    restored["channels"] += 1
                else:
                    failures.append(f"channel {ch_data.get('name')}: no result")
            except Exception as e:
                logger.warning("Restore channel %s failed: %s", ch_data.get("name"), e)
                failures.append(f"channel {ch_data.get('name')}: {e}")
            counter += 1
            await _pace(counter)

        # Restore emojis (name + image only; role restrictions are not restored)
        for e_data in backup.get("emojis", []):
            try:
                created = await _safe_call(lambda e=e_data: guild.create_custom_emoji(
                    name=e["name"], image=e["image"],
                ))
                if created is not None:
                    restored["emojis"] += 1
                else:
                    failures.append(f"emoji {e_data.get('name')}: no result")
            except Exception as e:
                logger.warning("Restore emoji %s failed: %s", e_data.get("name"), e)
                failures.append(f"emoji {e_data.get('name')}: {e}")
            counter += 1
            await _pace(counter)

        actual = {}
        try:
            actual["roles"] = len(
                [r for r in guild.roles if getattr(r, "name", "") != "@everyone"]
            )
        except Exception:
            actual["roles"] = None
        try:
            actual["categories"] = len(guild.categories)
        except Exception:
            actual["categories"] = None
        try:
            actual["channels"] = len(
                [c for c in guild.channels if not isinstance(c, discord.CategoryChannel)]
            )
        except Exception:
            actual["channels"] = None

        return {
            "expected": expected,
            "restored": restored,
            "actual": actual,
            "failures": failures,
        }

    # ==================== CREATE ====================

    @staticmethod
    def _map_overwrites(overwrites, role_map):
        """Chuyển overwrites theo map ID (tránh gán nhầm khi trùng tên).

        Keys can be ``discord.Role`` objects (guild cache) or plain role IDs
        (REST snapshot).
        """
        overwrites_to = {}
        for key, value in (overwrites or {}).items():
            if isinstance(key, discord.Role):
                role_id = key.id
            elif isinstance(key, int):
                role_id = key
            else:
                role_id = getattr(key, "id", None)
            if role_id is None:
                continue
            mapped = role_map.get(role_id)
            if mapped:
                overwrites_to[mapped] = value
        return overwrites_to

    @staticmethod
    def _map_backup_overwrites(overwrites_raw, role_id_map):
        """Map overwrites từ backup (key = role ID gốc dạng str) sang role mới."""
        result = {}
        for role_id_str, value in (overwrites_raw or {}).items():
            try:
                new_role = role_id_map.get(int(role_id_str))
            except (TypeError, ValueError):
                continue
            if new_role is not None:
                result[new_role] = value
        return result

    @staticmethod
    async def roles_create(guild_to: discord.Guild, guild_from):
        """Tạo roles từ server nguồn. Trả về map {role_id_nguồn: role_đích}."""
        if not _has_permission(guild_to, 'manage_roles'):
            return {}

        roles = _source_roles(guild_from)
        role_map = {}
        counter = 0

        for role in roles:
            try:
                created = await _safe_call(lambda r=role: guild_to.create_role(
                    name=r.name, permissions=r.permissions,
                    colour=r.colour, hoist=r.hoist, mentionable=r.mentionable,
                ))
                if created is not None:
                    role_map[role.id] = created
                else:
                    logger.warning("Tạo role %s không trả về kết quả", role.name)
                counter += 1
                await _pace(counter)
            except discord.Forbidden:
                logger.warning(f"Không thể tạo role: {role.name}")
            except Exception as e:
                logger.warning(f"Lỗi tạo role {role.name}: {e}")

        logger.info(f"Đã tạo {len(role_map)}/{len(roles)} roles")
        return role_map

    @staticmethod
    async def categories_create(guild_to: discord.Guild, guild_from, role_map=None):
        """Tạo categories từ server nguồn. Trả về map {category_id_nguồn: category_đích}."""
        if not _has_permission(guild_to, 'manage_channels'):
            return {}

        role_map = role_map or {}
        cat_map = {}
        counter = 0
        categories = _source_categories(guild_from)

        for category in categories:
            try:
                overwrites_to = CloneHandler._map_overwrites(category.overwrites, role_map)

                new_category = await _safe_call(lambda c=category, o=overwrites_to: guild_to.create_category(
                    name=c.name, overwrites=o,
                ))
                if new_category is not None:
                    cat_map[category.id] = new_category

                    try:
                        await new_category.edit(position=category.position)
                    except Exception:
                        pass
                else:
                    logger.warning("Tạo category %s không trả về kết quả", category.name)

                counter += 1
                await _pace(counter)

            except discord.Forbidden:
                logger.warning(f"Không thể tạo category: {category.name}")
            except Exception as e:
                logger.warning(f"Lỗi tạo category {category.name}: {e}")

        logger.info(f"Đã tạo {len(cat_map)}/{len(categories)} categories")
        return cat_map

    @staticmethod
    async def channels_create(guild_to: discord.Guild, guild_from, role_map=None, cat_map=None) -> tuple[int, int]:
        """Tạo text và voice channels từ server nguồn (match category theo ID).

        Returns ``(created, total)`` so callers can fail fast when the source has
        channels but none were created.
        """
        if not _has_permission(guild_to, 'manage_channels'):
            return 0, 0

        role_map = role_map or {}
        cat_map = cat_map or {}
        text_channels = _source_text_channels(guild_from)
        voice_channels = _source_voice_channels(guild_from)
        all_channels = _source_all_channels(guild_from)
        unsupported = len(all_channels) - len(text_channels) - len(voice_channels)
        if unsupported > 0:
            logger.warning(
                "Skipping %d unsupported source channel(s) (forum/media/etc.)",
                unsupported,
            )
        text_created = 0
        voice_created = 0
        counter = 0

        for channel_text in text_channels:
            try:
                category_id = getattr(channel_text, "category_id", None)
                if category_id is None:
                    category = getattr(channel_text, "category", None)
                    category_id = getattr(category, "id", None)
                category = cat_map.get(category_id) if category_id is not None else None
                overwrites_to = CloneHandler._map_overwrites(channel_text.overwrites, role_map)

                created = await _safe_call(lambda c=channel_text, cat=category, o=overwrites_to: guild_to.create_text_channel(
                    name=c.name, overwrites=o, position=c.position,
                    topic=c.topic, slowmode_delay=c.slowmode_delay,
                    nsfw=c.nsfw, category=cat,
                ))
                if created is not None:
                    text_created += 1
                else:
                    logger.warning("Tạo text channel %s không trả về kết quả", channel_text.name)

                counter += 1
                await _pace(counter)

            except discord.Forbidden:
                logger.warning(f"Không thể tạo text channel: {channel_text.name}")
            except Exception as e:
                logger.warning(f"Lỗi tạo text channel {channel_text.name}: {e}")

        for channel_voice in voice_channels:
            try:
                category_id = getattr(channel_voice, "category_id", None)
                if category_id is None:
                    category = getattr(channel_voice, "category", None)
                    category_id = getattr(category, "id", None)
                category = cat_map.get(category_id) if category_id is not None else None
                overwrites_to = CloneHandler._map_overwrites(channel_voice.overwrites, role_map)

                created = await _safe_call(lambda c=channel_voice, cat=category, o=overwrites_to: guild_to.create_voice_channel(
                    name=c.name, overwrites=o, position=c.position,
                    bitrate=min(c.bitrate, guild_to.bitrate_limit), user_limit=c.user_limit, category=cat,
                ))
                if created is not None:
                    voice_created += 1
                else:
                    logger.warning("Tạo voice channel %s không trả về kết quả", channel_voice.name)

                counter += 1
                await _pace(counter)

            except discord.Forbidden:
                logger.warning(f"Không thể tạo voice channel: {channel_voice.name}")
            except Exception as e:
                logger.warning(f"Lỗi tạo voice channel {channel_voice.name}: {e}")

        total = len(all_channels)
        created = text_created + voice_created
        logger.info(
            "Đã tạo %d/%d channels (%d text, %d voice)",
            created, total, text_created, voice_created,
        )
        return created, total

    # ==================== EMOJIS ====================

    @staticmethod
    async def emojis_delete(guild_to: discord.Guild) -> int:
        """Xóa toàn bộ custom emoji trong server đích."""
        if not _has_permission(guild_to, 'manage_emojis'):
            return 0

        deleted = 0
        counter = 0
        for emoji in list(guild_to.emojis):
            try:
                await _safe_call(emoji.delete)
                deleted += 1
                counter += 1
                await _pace(counter)
            except discord.Forbidden:
                logger.warning(f"Không thể xóa emoji: {emoji.name}")
            except Exception as e:
                logger.warning(f"Lỗi xóa emoji {emoji.name}: {e}")

        logger.info(f"Đã xóa {deleted} emojis")
        return deleted

    @staticmethod
    async def emojis_create(guild_to: discord.Guild, guild_from) -> int:
        """Copy toàn bộ custom emoji từ server nguồn sang server đích."""
        if not _has_permission(guild_to, 'manage_emojis'):
            return 0

        created = 0
        counter = 0
        emojis = _source_emojis(guild_from)
        for emoji in emojis:
            try:
                image = await emoji.read()
                result = await _safe_call(
                    lambda e=emoji, img=image: guild_to.create_custom_emoji(
                        name=e.name, image=img
                    )
                )
                if result is not None:
                    created += 1
                else:
                    logger.warning("Tạo emoji %s không trả về kết quả", emoji.name)
                counter += 1
                await _pace(counter)
            except discord.Forbidden:
                logger.warning(f"Không thể tạo emoji: {emoji.name}")
            except Exception as e:
                logger.warning(f"Lỗi tạo emoji {emoji.name}: {e}")

        logger.info(f"Đã tạo {created}/{len(emojis)} emojis")
        return created

    # ==================== SELECTIVE CLONE ====================

    @staticmethod
    async def clone_selective(
        guild_to: discord.Guild,
        guild_from: discord.Guild,
        options: dict | None = None,
        source_snapshot: SourceSnapshot | dict | None = None,
        progress=None,
        stats: dict | None = None,
    ) -> tuple[bool, str]:
        """Clone only the enabled sections.

        options = {"info": bool, "structure": bool, "emojis": bool}
        - info: server name + icon
        - structure: roles + categories + channels (interdependent)
        - emojis: custom emojis

        ``source_snapshot`` is used instead of ``guild_from`` for structure and
        emoji data when the guild cache is incomplete. ``progress`` is called as
        ``progress(step, done, total)``; ``stats`` is filled with per-section
        created/total counts for the dashboard result.
        """
        options = options or {}
        info = bool(options.get("info"))
        structure = bool(options.get("structure"))
        emojis = bool(options.get("emojis"))

        if not any((info, structure, emojis)):
            return False, "No clone options selected"

        # Pre-check every permission before touching the target. Previously a
        # missing manage_roles permission only surfaced after channels/categories
        # had already been deleted.
        required = []
        if info:
            required.append("manage_guild")
        if structure:
            required.extend(["manage_channels", "manage_roles"])
        if emojis:
            required.append("manage_emojis")
        required = list(dict.fromkeys(required))
        missing = _missing_permissions(guild_to, required)
        if missing:
            return False, (
                "Missing permissions in target server: " + ", ".join(missing)
            )

        source = (
            _coerce_source_snapshot(source_snapshot)
            if source_snapshot is not None
            else guild_from
        )
        source_roles = _source_roles(source)
        source_categories = _source_categories(source)
        source_channels = _source_channels(source)
        source_emojis = _source_emojis(source)

        # Safety cap: at the paced rate a huge source would run for hours and
        # still resemble a mass takeover. Refuse before touching the target.
        expected_items = 0
        if structure:
            expected_items += (
                len(source_roles) + len(source_categories) + len(source_channels)
            )
        if emojis:
            expected_items += len(source_emojis)
        if expected_items > CLONE_MAX_ITEMS:
            return False, (
                f"Source has {expected_items} items (cap {CLONE_MAX_ITEMS}) — "
                "split the clone into smaller runs"
            )

        # Never wipe the target based on an empty/partial source cache.
        if structure and not source_roles and not source_channels:
            return False, (
                "Source server has no roles or channels — refusing to delete "
                "target (source data unavailable?)"
            )
        if structure and not source_channels and _source_all_channels(source):
            return False, (
                "Source server has only unsupported channel types — refusing to "
                "delete target channels"
            )
        if structure and not source_channels:
            logger.warning(
                "Source server has no text/voice channels; target channels will be deleted"
            )
        if emojis and not source_emojis:
            return False, (
                "Source server has no emojis — refusing to delete target emojis "
                "(source data unavailable?)"
            )

        stats = stats if stats is not None else {}
        stats.update(
            {
                "roles_created": 0,
                "roles_total": len(source_roles) if structure else 0,
                "categories_created": 0,
                "categories_total": len(source_categories) if structure else 0,
                "channels_created": 0,
                "channels_total": len(source_channels) if structure else 0,
                "emojis_created": 0,
                "emojis_total": len(source_emojis) if emojis else 0,
            }
        )

        backup = (
            CloneHandler.backup_guild_state(guild_to) if structure else None
        )
        if emojis:
            if backup is None:
                # Emoji-only clone: keep structure lists empty so rollback does
                # not recreate roles/categories/channels that were never deleted.
                backup = {
                    "name": guild_to.name,
                    "icon": None,
                    "roles": [],
                    "categories": [],
                    "channels": [],
                }
            try:
                backup["emojis"] = await CloneHandler.backup_emojis(guild_to)
            except Exception as e:
                logger.warning("Emoji backup failed: %s", e)
                backup["emojis"] = []
        mutated = False

        async def rollback(message):
            if backup is None or not mutated:
                return message
            try:
                report = await CloneHandler.restore_guild_state(guild_to, backup)
                report = report or {}
                note = _format_rollback(report)
                if report.get("failures"):
                    logger.error("Rollback incomplete: %s", note)
                else:
                    logger.info("Rollback completed: %s", note)
                return f"{message} | {note}"
            except Exception as rollback_err:
                logger.error("Rollback failed: %s", rollback_err, exc_info=True)
                return f"{message} | rollback failed: {rollback_err}"

        try:
            if info:
                if not await CloneHandler.guild_edit(guild_to, guild_from):
                    return False, await rollback(
                        "Could not edit server info "
                        "(missing manage_guild permission?)"
                    )
                if structure:
                    mutated = True

            if structure:
                mutated = True
                await CloneHandler.channels_delete(guild_to)
                await CloneHandler.categories_delete(guild_to)
                await CloneHandler.roles_delete(guild_to)

                role_map = await CloneHandler.roles_create(guild_to, source)
                stats["roles_created"] = len(role_map)
                _emit_progress(
                    progress, "creating roles", len(role_map), len(source_roles)
                )
                if source_roles and not role_map:
                    return False, await rollback(
                        f"Could not create roles (0/{len(source_roles)}) — "
                        "check permissions/rate limits"
                    )

                cat_map = await CloneHandler.categories_create(
                    guild_to, source, role_map
                )
                stats["categories_created"] = len(cat_map)
                _emit_progress(
                    progress,
                    "creating categories",
                    len(cat_map),
                    len(source_categories),
                )
                if source_categories and not cat_map:
                    return False, await rollback(
                        f"Could not create categories (0/{len(source_categories)}) — "
                        "check permissions/rate limits"
                    )

                channels_created, channels_total = await CloneHandler.channels_create(
                    guild_to, source, role_map, cat_map
                )
                stats["channels_created"] = channels_created
                stats["channels_total"] = channels_total
                _emit_progress(
                    progress, "creating channels", channels_created, channels_total
                )
                if channels_total and not channels_created:
                    return False, await rollback(
                        f"Could not create channels (0/{channels_total}) — "
                        "check permissions/rate limits"
                    )

            if emojis:
                mutated = True
                await CloneHandler.emojis_delete(guild_to)
                created = await CloneHandler.emojis_create(guild_to, source)
                stats["emojis_created"] = created
                _emit_progress(
                    progress, "copying emojis", created, len(source_emojis)
                )
                if source_emojis and created == 0:
                    return False, await rollback(
                        f"Could not create emojis (0/{len(source_emojis)}) — "
                        "check permissions/rate limits"
                    )

            return True, ""

        except asyncio.CancelledError:
            logger.warning("Selective clone cancelled — rolling back")
            try:
                await rollback("cancelled")
            except Exception as rollback_err:
                logger.error(
                    "Rollback failed after cancellation: %s",
                    rollback_err,
                    exc_info=True,
                )
            raise
        except Exception as e:
            logger.error(f"Selective clone failed — rolling back: {e}")
            return False, await rollback(str(e))

    # ==================== FULL CLONE (với rollback) ====================

    @staticmethod
    async def clone_full(guild_to: discord.Guild, guild_from: discord.Guild) -> tuple[bool, str]:
        """
        Clone toàn bộ server: info + roles + categories + channels.
        Trả về (success, error_message).
        Tự động rollback nếu fail giữa chừng.
        """
        # Pre-check: source phải có nội dung
        if not guild_from.roles or len([r for r in guild_from.roles if r.name != "@everyone"]) == 0:
            return False, "Source server không có roles nào"

        # Backup trước khi xóa
        backup = CloneHandler.backup_guild_state(guild_to)

        try:
            # Step 1: Edit server info
            if not await CloneHandler.guild_edit(guild_to, guild_from):
                logger.warning("guild_edit failed — tiếp tục clone")

            # Step 2: Delete channels (trước categories vì channel overwrites cần role)
            await CloneHandler.channels_delete(guild_to)

            # Step 3: Delete categories
            await CloneHandler.categories_delete(guild_to)

            # Step 4: Delete roles (sau channels vì channel overwrites cần role reference)
            await CloneHandler.roles_delete(guild_to)

            # Step 5: Create roles
            role_map = await CloneHandler.roles_create(guild_to, guild_from)

            # Step 6: Create categories
            cat_map = await CloneHandler.categories_create(guild_to, guild_from, role_map)

            # Step 7: Create channels
            channels_created, channels_total = await CloneHandler.channels_create(
                guild_to, guild_from, role_map, cat_map
            )
            if channels_total and not channels_created:
                return False, (
                    f"Could not create channels (0/{channels_total}) — "
                    "check permissions/rate limits"
                )

            return True, ""

        except Exception as e:
            logger.error(f"Clone fail — đang rollback: {e}")
            try:
                await CloneHandler.restore_guild_state(guild_to, backup)
                logger.info("Rollback hoàn tất")
            except Exception as rollback_err:
                logger.error(f"Rollback cũng fail: {rollback_err}")
            return False, str(e)
