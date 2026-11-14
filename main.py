"""
Discord Selfbot - Main Entry Point
Refactored with Cog Architecture
"""

import os
import sys
import json
import math
import random
import tempfile
import time
import logging
import atexit
from datetime import datetime
from io import BytesIO
from pathlib import Path

import discord
from discord.ext import commands, tasks
from pystyle import Center, Colorate, Colors
from colorama import init as colorama_init
from src.data_store import migrate_legacy
from src.single_instance import (
    acquire_with_cleanup,
    release_single_instance_lock,
)
from src.dashboard_launcher import (
    ask_open_dashboard,
    start_dashboard,
    stop_handles,
)
from src.dashboard_sync import (
    RUNTIME_STATE_PATH,
    apply_runtime_state,
    consume_reload_request,
    record_reload_result,
    record_sync_error,
    record_sync_ok,
    write_status,
)
from src.http_client import close_session
from src.retry_policy import (
    MAX_NETWORK_RETRIES,
    classify_failure,
    retry_delay,
)
from src.utils import try_delete

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ Pillow not installed. Image help will be disabled.")
    print("Install: pip install pillow")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
logging.getLogger('discord').setLevel(logging.WARNING)

colorama_init()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
CONFIG_PATH = "config.json"
DATA_DIR = "data"

os.makedirs(DATA_DIR, exist_ok=True)

# ==================== CONFIG LOADER ====================

def load_config(exit_on_error=True, path=None):
    """Load configuration from JSON file."""
    cfg_path = path or CONFIG_PATH
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Config file not found: {cfg_path}")
        if exit_on_error:
            sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {cfg_path} — {e}")
        if exit_on_error:
            sys.exit(1)
    return None

def save_config(config):
    """Save configuration to JSON file atomically."""
    temp_path = None
    try:
        directory = os.path.dirname(os.path.abspath(CONFIG_PATH)) or "."
        handle_fd, temp_path = tempfile.mkstemp(
            prefix="config.", suffix=".tmp", dir=directory
        )
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, CONFIG_PATH)
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

# ==================== IMAGE GENERATOR ====================

# --- moondark help tokens ---
HELP_BG_TOP = (16, 18, 24)
HELP_BG_BOT = (26, 29, 37)
HELP_TITLE_TOP = (240, 235, 221)      # ivory
HELP_TITLE_BOT = (217, 185, 140)      # champagne
HELP_PILL_TEXT = (234, 230, 218)
HELP_TEXT_DESC = (169, 176, 188)
HELP_TEXT_FOOT = (139, 146, 158)
HELP_FRAME = (240, 235, 221, 22)
HELP_ACCENT_FALLBACK = (176, 180, 190)

COG_ACCENTS = {
    "afk": (155, 170, 196),
    "automess": (168, 195, 160),
    "general": (143, 189, 179),
    "moderation": (210, 160, 160),
    "presence": (214, 188, 142),
    "reactions": (210, 179, 107),
    "utility": (201, 163, 137),
    "voice": (159, 184, 208),
}

COMMAND_ICONS = {
    "join": "🎧",
    "leave": "🚪",
    "play": "🎵",
    "sb_list": "📋",
    "soundboard": "🎚",
    "afk": "😴",
    "ar": "💬",
    "ar_list": "📋",
    "auto_mess": "🔁",
    "clear": "🧹",
    "serverinfo": "🏠",
    "userinfo": "👤",
    "syncstatus": "🔄",
    "ban": "🔨",
    "unban": "♻️",
    "nuke": "💥",
    "leave_groups": "🚪",
    "clear_friends": "👥",
    "clear_dms": "📩",
    "rotate": "🔄",
    "spotify": "🎧",
    "rpc": "🎮",
    "react": "⚡",
    "weather": "🌤",
    "genimg": "🎨",
    "emoji": "😀",
    "clone": "🧬",
    "help": "📖",
    "reload": "🔄",
    "prefix": "✏️",
    "ping": "🏓",
}


def generate_help_image(cog_name, commands_data, prefix):
    """Render a moondark help card for one cog and return a PNG BytesIO."""
    if not PIL_AVAILABLE:
        return None

    try:
        accent = COG_ACCENTS.get(str(cog_name).lower(), HELP_ACCENT_FALLBACK)
        commands = list(commands_data)
        count = len(commands)

        width = 1000
        card_x0, card_x1 = 80, 920
        card_h, card_step = 76, 90
        header_h = 158
        footer_h = 90
        text_x = 156
        text_max_x = 900
        text_width = text_max_x - text_x
        height = header_h + count * card_step + footer_h

        def load_font(filename, size, bold=False):
            candidates = [
                "C:/Windows/Fonts/" + filename,
                filename,
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            for path in candidates:
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
            return ImageFont.load_default()

        def load_emoji_font(size):
            # Only the color emoji face; if it is missing the badge falls back
            # to an accent circle rather than rendering tofu boxes.
            for path in ("C:/Windows/Fonts/seguiemj.ttf", "seguiemj.ttf"):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
            return None

        title_font = load_font("segoeuib.ttf", 46, bold=True)
        pill_font = load_font("segoeui.ttf", 17)
        name_fonts = [
            load_font("seguisb.ttf", 21, bold=True),
            load_font("seguisb.ttf", 19, bold=True),
            load_font("seguisb.ttf", 17, bold=True),
        ]
        desc_font = load_font("segoeui.ttf", 17)
        foot_font = load_font("segoeui.ttf", 15)
        emoji_font = load_emoji_font(26)

        def lighten(color, factor=0.28):
            return tuple(int(v + (255 - v) * factor) for v in color)

        def vgrad(w, h, top, bottom):
            col = Image.new("RGB", (1, h))
            for y in range(h):
                t = y / max(1, h - 1)
                col.putpixel((0, y), tuple(
                    int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)
                ))
            return col.resize((w, h))

        def hgrad(w, h, c1, c2):
            row = Image.new("RGB", (w, 1))
            for x in range(w):
                t = x / max(1, w - 1)
                row.putpixel((x, 0), tuple(
                    int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)
                ))
            return row.resize((w, h)).convert("RGBA")

        def fade_alpha(image, factor):
            r, g, b, a = image.split()
            a = a.point(lambda v: int(v * factor))
            return Image.merge("RGBA", (r, g, b, a))

        def rounded_mask(size, radius):
            mask = Image.new("L", size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255
            )
            return mask

        def emoji_tile(emoji, font):
            # Render on a padded canvas, then crop to the real ink. This keeps
            # variation-selector glyphs (✉️, ♻️, ✏️) centred instead of using
            # their double-wide advance box.
            size = max(48, int(getattr(font, "size", 26)) * 3)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            drawer = ImageDraw.Draw(canvas)
            try:
                drawer.text(
                    (size // 2, size // 2),
                    emoji,
                    font=font,
                    anchor="mm",
                    embedded_color=True,
                )
            except Exception:
                try:
                    drawer.text(
                        (size // 2, size // 2),
                        emoji,
                        font=font,
                        anchor="mm",
                        fill=(255, 255, 255, 255),
                    )
                except Exception:
                    drawer.text(
                        (4, 4),
                        emoji,
                        font=font,
                        fill=(255, 255, 255, 255),
                    )
            bbox = canvas.getbbox()
            if not bbox:
                return None
            tile = canvas.crop(bbox)
            r, g, b, a = tile.split()
            rgb = Image.merge("RGB", (r, g, b))
            rgb = ImageEnhance.Color(rgb).enhance(0.72)
            rgb = ImageEnhance.Brightness(rgb).enhance(1.18)
            r, g, b = rgb.split()
            return Image.merge("RGBA", (r, g, b, a))

        def make_bg(w, h):
            bg = vgrad(w, h, HELP_BG_TOP, HELP_BG_BOT).convert("RGBA")

            moon = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            mx, my = int(w * 0.72), int(h * 0.10)
            ImageDraw.Draw(moon).ellipse(
                [mx - 190, my - 190, mx + 190, my + 190],
                fill=(232, 226, 208, 22),
            )
            bg = Image.alpha_composite(
                bg, moon.filter(ImageFilter.GaussianBlur(110))
            )

            warm = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(warm).ellipse(
                [-200, h - 320, 300, h + 120], fill=(217, 185, 140, 12)
            )
            bg = Image.alpha_composite(
                bg, warm.filter(ImageFilter.GaussianBlur(130))
            )

            grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gdraw = ImageDraw.Draw(grid)
            for x in range(0, w, 48):
                gdraw.line([(x, 0), (x, h)], fill=(255, 255, 255, 6))
            for y in range(0, h, 48):
                gdraw.line([(0, y), (w, y)], fill=(255, 255, 255, 6))
            bg = Image.alpha_composite(bg, grid)

            rng = random.Random(42)
            stars = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(stars)
            for _ in range(46):
                sx = rng.randint(4, max(4, w - 4))
                sy = rng.randint(4, max(4, h - 4))
                radius = rng.choice([1, 1, 1, 2])
                alpha = rng.randint(18, 70)
                color = rng.choice([(235, 230, 215), (217, 185, 140)])
                sdraw.ellipse(
                    [sx - radius, sy - radius, sx + radius, sy + radius],
                    fill=color + (alpha,),
                )
            bg = Image.alpha_composite(
                bg, stars.filter(ImageFilter.GaussianBlur(3))
            )
            bg = Image.alpha_composite(bg, stars)

            small = Image.new("L", (max(1, w // 20), max(1, h // 20)), 0)
            sw, sh = small.size
            ImageDraw.Draw(small).ellipse(
                [-w * 0.02, -h * 0.04, sw + w * 0.02, sh + h * 0.04],
                fill=255,
            )
            rad = small.resize((w, h)).filter(ImageFilter.GaussianBlur(60))
            dark = Image.new("RGBA", (w, h), (5, 6, 10, 255))
            dark.putalpha(rad.point(lambda v: int((255 - v) * 0.4)))
            return Image.alpha_composite(bg, dark)

        def gradient_title(img, text, cy, font, glow=14):
            cx = img.width // 2
            mask = Image.new("L", img.size, 0)
            ImageDraw.Draw(mask).text(
                (cx, cy), text, font=font, anchor="mm", fill=255
            )
            bbox = mask.getbbox()
            if not bbox:
                return
            grad = hgrad(
                bbox[2] - bbox[0],
                bbox[3] - bbox[1],
                HELP_TITLE_TOP,
                HELP_TITLE_BOT,
            )
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.paste(grad, (bbox[0], bbox[1]), mask.crop(bbox))
            img.alpha_composite(
                fade_alpha(layer.filter(ImageFilter.GaussianBlur(glow)), 0.55)
            )
            img.alpha_composite(layer)

        def draw_pill(img, text, cy, font):
            draw = ImageDraw.Draw(img)
            tw = draw.textlength(text, font=font)
            cx = img.width // 2
            box = [cx - tw / 2 - 20, cy - 17, cx + tw / 2 + 20, cy + 17]
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle(
                box,
                radius=17,
                fill=HELP_TITLE_BOT + (10,),
                outline=HELP_TITLE_BOT + (95,),
                width=1,
            )
            img.alpha_composite(
                fade_alpha(layer.filter(ImageFilter.GaussianBlur(6)), 0.45)
            )
            img.alpha_composite(layer)
            ImageDraw.Draw(img).text(
                (cx, cy), text, font=font, fill=HELP_PILL_TEXT, anchor="mm"
            )

        def glass_card(img, box, card_accent, radius=18):
            x0, y0, x1, y1 = box
            cw, ch = x1 - x0, y1 - y0

            shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(
                [x0 + 3, y0 + 12, x1 + 3, y1 + 12],
                radius=radius,
                fill=(0, 0, 0, 85),
            )
            img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))

            glass = img.crop(box).filter(ImageFilter.GaussianBlur(9))
            glass = ImageEnhance.Brightness(glass.convert("RGBA")).enhance(0.72)
            card = Image.alpha_composite(
                glass, Image.new("RGBA", (cw, ch), (12, 14, 19, 175))
            )
            mask = rounded_mask((cw, ch), radius)
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.paste(card, (x0, y0), mask)
            img.alpha_composite(layer)

            ring = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            ImageDraw.Draw(ring).rounded_rectangle(
                [0, 0, cw - 1, ch - 1],
                radius=radius,
                outline=card_accent + (120,),
                width=1,
            )
            glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            glow_layer.paste(
                fade_alpha(ring.filter(ImageFilter.GaussianBlur(5)), 0.55),
                (x0, y0),
                mask,
            )
            img.alpha_composite(glow_layer)
            ring_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ring_layer.paste(ring, (x0, y0), mask)
            img.alpha_composite(ring_layer)

        def icon_badge(img, cx, cy, emoji, font, card_accent, radius=23):
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                fill=card_accent + (24,),
                outline=card_accent + (150,),
                width=1,
            )
            img.alpha_composite(
                fade_alpha(layer.filter(ImageFilter.GaussianBlur(6)), 0.5)
            )
            img.alpha_composite(layer)
            if font is None:
                ImageDraw.Draw(img).ellipse(
                    [cx - 10, cy - 10, cx + 10, cy + 10],
                    fill=card_accent + (190,),
                )
                return
            tile = emoji_tile(emoji, font)
            if tile is None:
                ImageDraw.Draw(img).ellipse(
                    [cx - 10, cy - 10, cx + 10, cy + 10],
                    fill=card_accent + (190,),
                )
                return
            img.alpha_composite(
                tile,
                (int(cx - tile.width / 2), int(cy - tile.height / 2)),
            )

        def divider(img, y):
            grad = fade_alpha(
                hgrad(img.width - 200, 1, HELP_TITLE_BOT, HELP_TITLE_TOP),
                0.55,
            )
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.paste(grad, (100, y))
            img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2)))
            img.alpha_composite(layer)

        def frame(img):
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle(
                [5, 5, img.width - 6, img.height - 6],
                radius=24,
                outline=HELP_FRAME,
                width=1,
            )
            img.alpha_composite(layer)

        def fit_text(draw, text, font, max_width):
            if not text or max_width <= 0:
                return ""
            if draw.textlength(text, font=font) <= max_width:
                return text
            ellipsis = "…"
            if draw.textlength(ellipsis, font=font) > max_width:
                return ""
            low, high = 0, len(text)
            while low < high:
                mid = (low + high + 1) // 2
                trial = text[:mid].rstrip() + ellipsis
                if draw.textlength(trial, font=font) <= max_width:
                    low = mid
                else:
                    high = mid - 1
            head = text[:low].rstrip()
            if " " in head[8:]:
                head = head.rsplit(" ", 1)[0].rstrip()
            return (head + ellipsis) if head else ellipsis

        def parse_command(cmd_name, aliases, desc):
            desc = (desc or "").strip()
            signature = ""
            description = ""
            if desc.lower().startswith("usage:"):
                rest = desc[len("Usage:"):].lstrip(" ")
                signature, _, description = rest.partition(" — ")
                signature = signature.strip()
                description = description.strip()
            if not signature:
                signature = f"{prefix}{cmd_name}"
                if desc and not desc.lower().startswith("usage:"):
                    description = desc
                else:
                    description = ""
            if aliases:
                head = f"{prefix}{cmd_name}"
                if signature.startswith(head):
                    signature = head + f" ({aliases})" + signature[len(head):]
            return signature, description

        img = make_bg(width, height)
        gradient_title(img, f"{str(cog_name).upper()} COMMANDS", 64, title_font)
        label = "COMMAND" if count == 1 else "COMMANDS"
        draw_pill(img, f"{count} AVAILABLE {label}", 122, pill_font)

        name_color = lighten(accent)
        y = header_h
        for cmd_name, aliases, desc in commands:
            glass_card(img, (card_x0, y, card_x1, y + card_h), accent)
            mid = y + card_h // 2
            icon_badge(
                img,
                120,
                mid,
                COMMAND_ICONS.get(str(cmd_name).lower(), "•"),
                emoji_font,
                accent,
            )

            draw = ImageDraw.Draw(img)
            signature, description = parse_command(cmd_name, aliases, desc)

            sig_font = name_fonts[0]
            sig_width = draw.textlength(signature, font=sig_font)
            for candidate in name_fonts[1:]:
                if sig_width <= text_width:
                    break
                sig_font = candidate
                sig_width = draw.textlength(signature, font=sig_font)
            if sig_width > text_width:
                signature = fit_text(draw, signature, sig_font, text_width)
                sig_width = draw.textlength(signature, font=sig_font)

            # Fixed 14px gap, then the dash: the dash string itself carries the
            # trailing space, so the gap is not counted twice.
            sep_gap = 14
            sep = "— "
            sep_width = draw.textlength(sep, font=desc_font)
            desc_text = ""
            if description:
                budget = text_width - sig_width - sep_gap - sep_width
                desc_text = fit_text(draw, description, desc_font, budget)

            draw.text(
                (text_x, mid),
                signature,
                font=sig_font,
                fill=name_color,
                anchor="lm",
            )
            if desc_text:
                draw.text(
                    (text_x + sig_width + sep_gap, mid + 1),
                    sep + desc_text,
                    font=desc_font,
                    fill=HELP_TEXT_DESC,
                    anchor="lm",
                )
            y += card_step

        divider(img, y + 6)
        ImageDraw.Draw(img).text(
            (width // 2, y + 40),
            f"Usage: {prefix}<command>   |   Prefix: {prefix}",
            font=foot_font,
            fill=HELP_TEXT_FOOT,
            anchor="mm",
        )
        frame(img)

        img_bytes = BytesIO()
        img.convert("RGB").save(img_bytes, format="PNG", optimize=True)
        img_bytes.seek(0)
        return img_bytes

    except Exception as e:
        logger.error(f"Error generating help image: {e}")
        return None

# ==================== RPC IDENTITY SPOOF ====================
# Phải patch identify TRƯỚC khi bot connect lần đầu — patch trong cog (sau khi
# đã connect) sẽ không có tác dụng vì IDENTIFY chỉ gửi 1 lần lúc bắt đầu session.

from discord.gateway import DiscordWebSocket

SERVICE_IDENTIFY = {
    "meta":    {"os": "VR",      "browser": "Discord VR",      "device": "Discord VR"},
    "xbox":    {"os": "Xbox",    "browser": "Discord Xbox",    "device": "Discord Xbox"},
    "samsung": {"os": "Samsung", "browser": "Discord Samsung", "device": "Discord Samsung"},
    "ios":     {"os": "iOS",     "browser": "Discord iOS",     "device": "Discord iOS"},
    "android": {"os": "Android", "browser": "Discord Android", "device": "Discord Android"},
}

def _load_rpc_service():
    """Đọc field 'service' trong rich_presence.json để biết cần giả danh nền tảng nào."""
    try:
        with open("data/rich_presence.json", "r", encoding="utf-8") as f:
            rpc_cfg = json.load(f)
        return str(rpc_cfg.get("service", "")).lower()
    except Exception:
        return ""

_rpc_service = _load_rpc_service()
_identify_props = SERVICE_IDENTIFY.get(_rpc_service)

if _identify_props:
    async def _identify_spoofed(self):
        await self.send_as_json({
            "op": 2,
            "d": {
                "token": self.token,
                "capabilities": 16381,
                "properties": _identify_props,
                "compress": True,
                "large_threshold": 250,
            },
        })
    DiscordWebSocket.identify = _identify_spoofed
    logger.info(f"[RPC] Session will identify as platform: {_rpc_service}")
else:
    logger.info("[RPC] Not spoofing platform (empty/invalid service in rich_presence.json)")

# ==================== BOT SETUP ====================

config = load_config()
if config is None:
    logger.error("Could not load config.json — check that it exists and contains valid JSON")
    sys.exit(1)
PREFIX = config.get('prefix', '.')
TOKEN = config.get('token')

if not TOKEN:
    logger.error("No token found in config.json")
    sys.exit(1)

# Strip whitespace from token (common issue)
TOKEN = TOKEN.strip()

# Debug: Check token format (without exposing full token)
if TOKEN:
    logger.info(f"Token length: {len(TOKEN)} characters")

    if TOKEN.count('.') != 2:
        logger.warning("Token format may be incorrect (expected 2 dots for Discord token)")

# Create bot instance
bot = commands.Bot(
    description='BOT',
    command_prefix=PREFIX,
    self_bot=True,
    guild_subscriptions=True,      # Nhận message từ mọi channel trong server lớn
    chunk_guilds_at_startup=False, # Tránh timeout khi startup server 100+ channels
)
bot.remove_command('help')
bot._cogs_loaded_once = False

# Store config in bot instance
bot.config = config
bot.config_path = CONFIG_PATH

# ==================== OWNER-ONLY CHECK (Single-User Mode) ====================

@bot.check
async def owner_only(ctx):
    """Chỉ chủ token (chính tài khoản selfbot) được phép chạy lệnh.

    Đây là selfbot cá nhân — không whitelist nhiều người, không phân quyền.
    """
    return bool(bot.user and ctx.author.id == bot.user.id)

# ==================== EVENT HANDLERS ====================

_last_runtime_mtime = 0.0
_dashboard_info = None


def print_dashboard_info(info) -> None:
    """Print the dashboard URL + pairing code (survives on_ready's clear-screen)."""
    if not info:
        return
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"🌐 Dashboard : {info.get('web_url')}")
    code = info.get("pairing_code")
    if code:
        print(f"🔑 Pair code : {code}")
    else:
        print("🔑 Pair code : backend already running — use the code shown when it started")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


@tasks.loop(seconds=10)
async def dashboard_status_loop():
    """Publish an honest online status for the dashboard adapter."""
    write_status(bot)


@tasks.loop(seconds=2)
async def dashboard_state_loop():
    """Apply dashboard settings when runtime_state.json changes."""
    global _last_runtime_mtime
    utility_cog = bot.get_cog("Utility")
    clone_in_flight = bool(getattr(utility_cog, "clone_in_flight", False))
    if not clone_in_flight and consume_reload_request():
        try:
            ok_count, fail_count = await reload_all_cogs()
            record_reload_result(
                fail_count == 0,
                f"Reloaded {ok_count} cogs"
                + (f", {fail_count} failed" if fail_count else ""),
            )
        except Exception as exc:
            record_reload_result(False, f"Reload failed: {exc}")
    try:
        mtime = RUNTIME_STATE_PATH.stat().st_mtime
    except OSError:
        return
    if mtime <= _last_runtime_mtime:
        return
    try:
        state = json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
        await apply_runtime_state(bot, state)
    except Exception as exc:
        record_sync_error(exc)
        logger.warning("Dashboard state sync failed: %s", exc)
    else:
        _last_runtime_mtime = mtime
        record_sync_ok()


@bot.event
async def on_ready():
    """Bot ready event."""
    try:
        print('\033[2J\033[H', end='')  # ANSI clear — không spawn shell con mỗi reconnect
        
        print(
            Center.XCenter(
                Colorate.Vertical(
                    Colors.blue_to_cyan,
                    f"Logged in as {bot.user.name}",
                    1,
                )
            )
        )
        
        logger.info(f"Logged in as {bot.user.name} ({bot.user.id})")
        logger.info(f"Prefix: {PREFIX}")
        logger.info(f"Loaded {len(bot.cogs)} cogs")
        logger.info(f"Loaded {len(bot.commands)} commands")

        # Re-print dashboard URL + pairing code after the clear-screen so the
        # user can still see it (on_ready fires again on every reconnect).
        print_dashboard_info(_dashboard_info)
        
        # Load all cogs
        if not bot._cogs_loaded_once:
            # Adopt dpy-self's live client identity (Chrome version + build
            # number fetched at login) before cogs boot raw gateways, so every
            # session presents one consistent fingerprint.
            try:
                from src import client_identity

                client_identity.sync_from_headers(bot.http.headers)
            except Exception as exc:
                logger.warning("Client identity sync failed: %s", exc)
            # Startup hygiene: every automation feature starts OFF. Settings
            # (reasons, triggers, pools, emojis, cooldowns) are preserved; the
            # user enables what they want after the bot is running.
            try:
                from src.startup_reset import reset_features_to_off

                reset_summary = reset_features_to_off()
                logger.info(
                    "🔁 Startup reset (features OFF): %s", reset_summary
                )
            except Exception as exc:
                logger.warning("Startup reset failed: %s", exc)
            await load_cogs()
            bot._cogs_loaded_once = True
        
        # Store start time — chỉ set LẦN ĐẦU (on_ready fire lại mỗi reconnect)
        if not hasattr(bot, 'start_time'):
            bot.start_time = datetime.now()

        # Dashboard bridge: publish status + apply saved settings
        write_status(bot)
        if not dashboard_status_loop.is_running():
            dashboard_status_loop.start()
        if not dashboard_state_loop.is_running():
            dashboard_state_loop.start()

        global _last_runtime_mtime
        try:
            mtime = RUNTIME_STATE_PATH.stat().st_mtime
            if mtime > _last_runtime_mtime:
                state = json.loads(
                    RUNTIME_STATE_PATH.read_text(encoding="utf-8")
                )
                await apply_runtime_state(bot, state)
                _last_runtime_mtime = mtime
                record_sync_ok()
        except OSError:
            pass
        except Exception as exc:
            logger.warning("Dashboard state apply failed: %s", exc)

    except Exception as e:
        logger.error(f"Error in on_ready: {e}")

@bot.event
async def on_command(ctx):
    """Log every command invocation."""
    logger.debug(
        f"[COMMAND] {ctx.author.id} ({ctx.author.name}) used `{ctx.message.content}` "
        f"in #{getattr(ctx.channel, 'name', 'DM')}"
    )

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore command not found

    # Owner-only check failure (không phải lỗi Discord permission)
    if isinstance(error, commands.CheckFailure):
        if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions)):
            pass  # fall through and show error
        else:
            logger.warning(
                f"[OWNER-ONLY] {ctx.author.id} ({ctx.author.name}) tried to use a command — ignored"
            )
            return
    
    cmd_name = getattr(ctx.command, 'name', None) if ctx.command else 'None'
    invoked = getattr(ctx, 'invoked_with', 'None')
    logger.error(f"Command error: cmd={cmd_name} invoked={invoked!r} msg={getattr(ctx.message,'content',None)!r} error={error}")
    
    if ctx.author.id == bot.user.id:
        await try_delete(ctx.message)
    
    error_msg = str(error)
    if len(error_msg) > 200:
        error_msg = error_msg[:200] + "..."
    
    await ctx.send(f"❌ **Error:** {error_msg}", delete_after=10)

@bot.event
async def on_message(message):
    """Handle incoming messages."""
    if message.author.bot:
        return

    # Process commands
    await bot.process_commands(message)

# ==================== COG MANAGEMENT ====================

async def load_cogs():
    """Load all cogs from the cogs directory."""
    cogs_dir = "cogs"
    
    if not os.path.exists(cogs_dir):
        logger.warning(f"Cogs directory not found: {cogs_dir}")
        return
    
    loaded = 0
    failed = 0
    
    for filename in sorted(os.listdir(cogs_dir)):
        if filename.endswith('.py') and not filename.startswith('_'):
            cog_name = filename[:-3]
            try:
                ext_name = f"cogs.{cog_name}"
                if ext_name in bot.extensions:
                    continue
                await bot.load_extension(ext_name)
                logger.info(f"✅ Loaded cog: {cog_name}")
                loaded += 1
            except Exception as e:
                logger.error(f"❌ Failed to load cog {cog_name}: {e}")
                failed += 1
    
    logger.info(f"Cogs loaded: {loaded} | Failed: {failed}")

# ==================== RELOAD COMMAND ====================

def _rearm_auto_mess(bot):
    """Re-create the AutoMess broadcaster task after a cog reload."""
    auto_cog = bot.get_cog("AutoMess")
    if auto_cog is None:
        return
    cfg = (getattr(auto_cog, "data", {}) or {}).get("auto_mess_config", {}) or {}
    task = getattr(auto_cog, "auto_mess_task", None)
    if cfg.get("active") and (task is None or task.done()):
        # Fresh cog starts with _last_time_send = None → seed it so the first
        # send waits one interval instead of firing immediately.
        auto_cog._last_time_send = time.monotonic()
        auto_cog.auto_mess_task = bot.loop.create_task(auto_cog._auto_mess_loop())


async def reload_all_cogs() -> tuple[int, int]:
    """Reload config.json and every loaded cog extension without a restart.

    Returns ``(reloaded_count, failed_count)``.  Never raises.
    """
    global config, PREFIX

    reloaded = 0
    failed = 0

    try:
        new_config = load_config(exit_on_error=False)
        if new_config is None:
            failed += 1
            logger.error("Config reload failed: config.json invalid, keeping old config")
        else:
            config = new_config
            bot.config = config
            new_prefix = config.get('prefix', '.')
            if new_prefix != PREFIX:
                PREFIX = new_prefix
                bot.command_prefix = new_prefix
                logger.info(f"✅ Config reloaded (prefix → {new_prefix})")
            else:
                logger.info("✅ Config reloaded")
    except Exception as e:
        failed += 1
        logger.error(f"Config reload failed: {e}")

    for ext_name in list(bot.extensions):
        try:
            await bot.reload_extension(ext_name)
            reloaded += 1
            logger.info(f"✅ Reloaded: {ext_name}")
        except Exception as e:
            failed += 1
            logger.error(f"❌ Failed to reload {ext_name}: {e}")

    _rearm_auto_mess(bot)

    return reloaded, failed


@bot.command(name='reload', aliases=['load'])
async def reload_cmd(ctx, *targets: str):
    """Usage: {prefix}reload <file_name...> — load/reload config or cog (no extension needed)

Examples:
  {prefix}reload config            → reload config.json
  {prefix}reload afk               → load/reload cogs/afk.py
  {prefix}reload config afk voice  → reload multiple items at once
    """
    global config, PREFIX

    await try_delete(ctx.message)

    if not targets:
        cog_names = ", ".join(sorted(
            os.path.splitext(f)[0]
            for f in os.listdir("cogs")
            if f.endswith(".py") and not f.startswith("_")
        ))
        return await ctx.send(
            f"❓ **Usage:** `{ctx.prefix}reload <file_name...>` (no extension needed)\n"
            f"• `config` → config.json\n"
            f"• Available cogs: `{cog_names}`\n"
            f"Example: `{ctx.prefix}reload config` | `{ctx.prefix}reload afk voice`",
            delete_after=15,
        )

    results = []
    for raw in targets:
        name = raw.strip().lower().rstrip(',')
        for suffix in (".py", ".json"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break

        # Không hỗ trợ reload all — bắt buộc nêu rõ tên
        if name in ("all", "reload_all", "rall"):
            results.append("❌ `all` is not supported — list each name (e.g. `config afk voice`)")
            continue

        # 1. config.json
        if name == "config":
            try:
                new_config = load_config(exit_on_error=False)
                if new_config is None:
                    results.append("❌ Config: invalid JSON (kept old config)")
                    logger.error("Config reload failed: config.json invalid, keeping old config")
                else:
                    config = new_config
                    bot.config = config
                    new_prefix = config.get('prefix', '.')
                    if new_prefix != PREFIX:
                        PREFIX = new_prefix
                        bot.command_prefix = new_prefix
                        results.append(f"✅ Config (prefix → `{new_prefix}`)")
                    else:
                        results.append("✅ Config")
                    logger.info("✅ Config reloaded")
            except Exception as e:
                results.append(f"❌ Config: {str(e)[:50]}")
                logger.error(f"Config reload failed: {e}")
            continue

        # 2. Cog: cogs/<name>.py
        cog_path = os.path.join("cogs", f"{name}.py")
        if not os.path.exists(cog_path):
            results.append(f"❌ `{name}`: `cogs/{name}.py` not found")
            continue

        ext_name = f"cogs.{name}"
        was_loaded = ext_name in bot.extensions
        try:
            if was_loaded:
                await bot.reload_extension(ext_name)
                results.append(f"✅ Cog `{name}` (reloaded)")
                logger.info(f"✅ Reloaded: {ext_name}")
            else:
                await bot.load_extension(ext_name)
                results.append(f"✅ Cog `{name}` (loaded)")
                logger.info(f"✅ Loaded: {ext_name}")
        except Exception as e:
            action = "reload" if was_loaded else "load"
            results.append(f"❌ Cog `{name}` ({action}): {str(e)[:80]}")
            logger.error(f"Failed to {action} {ext_name}: {e}")

    # Reloading auto_mess cancels its broadcaster via cog_unload — re-arm it
    # when the saved config is still active (same pattern as dashboard_sync).
    _rearm_auto_mess(bot)

    await ctx.send("**🔄 RELOAD**\n" + "\n".join(f"• {r}" for r in results), delete_after=15)

# ==================== BASIC COMMANDS ====================

# One emoji per feature module for the help menu (fallback: 📦).
COG_EMOJIS = {
    "afk": "😴",
    "automess": "💬",
    "general": "ℹ️",
    "moderation": "⚔️",
    "presence": "🎭",
    "reactions": "⚡",
    "utility": "🎨",
    "voice": "🎧",
}

@bot.command(name='help', aliases=['cmd', 'h'])
async def help_command(ctx, category: str = None):
    """Usage: {prefix}help [cog] — main menu or detailed help for a cog"""
    logger.debug(f"[HELP] Invoked by {ctx.author.id} ({ctx.author.name}), category={category!r}")
    if ctx.author.id == bot.user.id:
        await try_delete(ctx.message)
    
    try:
        await ctx.send("⏳ Loading help...", delete_after=5)
        logger.debug(f"[HELP] Ack sent to {ctx.author.id}")
    except Exception as e:
        logger.error(f"[HELP] Failed to send ack: {e}")
    
    try:
        if not category:
            # Main menu - text version
            cogs_info = []
            
            # Danh sách các cog có trong bot — mỗi module một emoji đại diện
            for cog_name in sorted(bot.cogs.keys()):
                cog = bot.cogs[cog_name]
                if cog.get_commands():
                    emoji = COG_EMOJIS.get(cog_name.lower(), "📦")
                    cogs_info.append(f"{emoji} {cog_name.lower()}")
            
            # Chia thành 2 cột
            half = (len(cogs_info) + 1) // 2
            col1 = cogs_info[:half]
            col2 = cogs_info[half:]
            
            help_text = f"""```
🤖 SELFBOT MENU | Prefix: {PREFIX}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 COGS:
"""
            # Ghép 2 cột
            for i in range(max(len(col1), len(col2))):
                left = col1[i] if i < len(col1) else ""
                right = col2[i] if i < len(col2) else ""
                help_text += f"\n{left:<30} {right}"
            
            help_text += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ COMMANDS:
  📖 {PREFIX}help <cog>     Detailed help for a cog
  🔄 {PREFIX}reload <name>  Reload config/cog by file name
  🏓 {PREFIX}ping           Check latency
  ✏️ {PREFIX}prefix <new>   Change prefix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```"""
            await ctx.send(help_text, delete_after=60)
        else:
            # Category specific help - IMAGE VERSION
            # Try to find cog by name (case-insensitive)
            cog = None
            category_lower = category.lower()
            for cog_name, cog_obj in bot.cogs.items():
                if cog_name.lower() == category_lower:
                    cog = cog_obj
                    break
            
            if not cog:
                await ctx.send(f"❌ Cog not found: `{category}`\nUse `{PREFIX}help` to list cogs", delete_after=10)
                return
            
            commands_list = cog.get_commands()
            if not commands_list:
                await ctx.send(f"❌ Cog `{category}` has no commands.", delete_after=10)
                return
            
            # Prepare commands data
            commands_data = []
            for cmd in sorted(commands_list, key=lambda x: x.name):
                # Aliases
                aliases = ", ".join(cmd.aliases) if cmd.aliases else ""
                
                # Description - chỉ lấy dòng đầu + thay prefix thật
                desc = cmd.help or cmd.brief or "No description"
                desc = desc.split('\n')[0].strip()
                desc = desc.replace("{prefix}", PREFIX)
                
                commands_data.append((cmd.name, aliases, desc))
            
            # Try to generate image
            if PIL_AVAILABLE:
                img_bytes = generate_help_image(category, commands_data, PREFIX)
                
                if img_bytes:
                    try:
                        # Send image
                        file = discord.File(img_bytes, filename=f"{category}_help.png")
                        await ctx.send(file=file)
                        return
                    except Exception as img_err:
                        logger.warning(f"Help image send failed: {img_err}")
            
            # Fallback to text if image generation failed or send failed
            help_text = f"**{category.upper()} COMMANDS**\n"
            help_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n```\n"
            
            for cmd_name, aliases, desc in commands_data:
                if aliases:
                    cmd_display = f"{cmd_name} ({aliases})"
                else:
                    cmd_display = cmd_name
                
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                
                help_text += f"{PREFIX}{cmd_display}\n"
                help_text += f"  └─ {desc}\n\n"
            
            help_text += "```\n"
            help_text += f"💡 **Tip:** Type `{PREFIX}<command>` to run a command"
            
            await ctx.send(help_text, delete_after=60)
    except Exception as e:
        logger.error(f"[HELP] Unexpected error: {e}", exc_info=True)
        try:
            await ctx.send(f"❌ Error rendering help: `{e}`", delete_after=15)
        except Exception:
            pass

@bot.command(name='prefix')
async def change_prefix(ctx, new_prefix: str):
    """Usage: {prefix}prefix <new_prefix> — change prefix (saved to config.json)"""
    await try_delete(ctx.message)
    
    import re as _re
    if not new_prefix or new_prefix.isspace() or len(new_prefix) > 5 or _re.search(r'\s', new_prefix):
        return await ctx.send("❌ Invalid prefix (1-5 characters, no spaces).", delete_after=8)

    global PREFIX
    PREFIX = new_prefix
    bot.command_prefix = new_prefix

    # Re-read config.json so dashboard-made changes (e.g. voice tokens) are not
    # reverted by writing back the snapshot loaded at process start.  Hold the
    # same lock cogs/voice.py uses for its token evictions so a concurrent
    # eviction cannot be reverted (or the new prefix clobbered).
    try:
        from cogs.voice import _CONFIG_LOCK
    except Exception:
        _CONFIG_LOCK = None

    def _apply_prefix():
        fresh_config = load_config(exit_on_error=False)
        if not isinstance(fresh_config, dict):
            fresh_config = dict(bot.config)
        fresh_config['prefix'] = new_prefix
        save_config(fresh_config)
        return fresh_config

    if _CONFIG_LOCK is None:
        fresh_config = _apply_prefix()
    else:
        with _CONFIG_LOCK:
            fresh_config = _apply_prefix()
    bot.config = fresh_config
    
    await ctx.send(f"✅ Prefix changed to: `{new_prefix}`", delete_after=10)

@bot.command(name='ping')
async def ping(ctx):
    """Usage: {prefix}ping — check latency"""
    await try_delete(ctx.message)
    
    latency_ms = round(bot.latency * 1000) if math.isfinite(bot.latency) else None
    if latency_ms is None:
        return await ctx.send("🏓 Pong! (waiting for the first heartbeat)", delete_after=10)
    await ctx.send(f"🏓 **Pong!** Latency: {latency_ms}ms", delete_after=10)

# ==================== MAIN ENTRY POINT ====================

if __name__ == "__main__":
    # Chặn tuyệt đối 2 process bot cùng token — 2 gateway session cùng token
    # khiến Discord invalidate session (close 4003/4004).
    _instance_lock, _killed_pids = acquire_with_cleanup(
        Path(__file__).resolve().parent / "data" / "bot.lock",
        Path(__file__).resolve().parent / "data" / "bot.pid",
    )
    if _killed_pids:
        print(f"🧹 Stopped old bot instance(s): {', '.join(str(p) for p in _killed_pids)}")
    if _instance_lock is None:
        print("❌ Another bot instance is still running (could not stop it). Stop it manually and retry.")
        sys.exit(1)
    atexit.register(release_single_instance_lock)

    _dashboard = None

    try:
        # 0. Reset data files về trạng thái gốc
        print("🔄 Preparing data files...")
        migrate_legacy()

        # 1. Kiểm tra token
        if not config.get("token"):
            print("❌ TOKEN NOT FOUND in config.json!")
            print("Please add your token to config.json")
            sys.exit(1)
        
        TOKEN = config.get("token").strip()
        
        if not TOKEN or len(TOKEN) < 50:
            print("❌ INVALID TOKEN! (too short or empty)")
            sys.exit(1)

        if not PIL_AVAILABLE:
            print("\n⚠️  WARNING: Pillow not installed")
            print("Image help will use text fallback")
            print("Install with: pip install pillow\n")

        print("🚀 Starting bot...")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if ask_open_dashboard(sys.argv[1:]):
            _dashboard = start_dashboard(
                repo_root=Path(__file__).resolve().parent,
                web_dir=Path(__file__).resolve().parent / "dashboard" / "apps" / "web",
                open_browser="--no-browser" not in sys.argv[1:],
            )
            _dashboard_info = {
                "web_url": _dashboard.web_url,
                "pairing_code": _dashboard.pairing_code,
            }
            print_dashboard_info(_dashboard_info)

        attempt = 0
        while True:
            try:
                bot.run(TOKEN)
                break  # bot.close()/run kết thúc bình thường
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if classify_failure(e) == "auth":
                    print(f"\n❌ LOGIN FAILED: {type(e).__name__}: {e}")
                    print("Token is invalid or has been revoked — NOT retrying.")
                    print("Repeated login attempts can trigger a forced password reset.")
                    print("Update the token in config.json, then restart the bot.")
                    sys.exit(1)

                attempt += 1
                if attempt > MAX_NETWORK_RETRIES:
                    print(f"\n❌ {type(e).__name__}: {e}")
                    print("Too many consecutive failures — stopping.")
                    sys.exit(1)

                import traceback
                traceback.print_exc()
                delay = retry_delay(attempt - 1)
                print(f"\n⚠️ BOT CRASH: {type(e).__name__}: {e}")
                print(
                    f"🔄 Retry attempt {attempt}/{MAX_NETWORK_RETRIES} "
                    f"in {delay:.0f}s... (Ctrl+C to exit)"
                )
                time.sleep(delay)

        print("ℹ️ Bot stopped")
        sys.exit(0)
        
    except KeyboardInterrupt:
        # Best-effort dọn dẹp khi dừng bằng Ctrl+C
        try:
            from cogs.voice import voice_manager
            voice_manager.stop_all()
        except Exception:
            pass
        try:
            import asyncio
            asyncio.run(close_session())
        except Exception:
            pass
        print("\nℹ️ Bot stopped")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        if _dashboard is not None:
            try:
                stop_handles(_dashboard)
            except Exception as e:
                logger.warning("Failed to stop dashboard: %s", e)