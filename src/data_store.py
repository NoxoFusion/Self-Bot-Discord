"""
Centralized data storage — atomic state persistence cho selfbot cá nhân.

state.json : afk, afk_config, auto (auto_mess config + message pool), reactions
"""

import asyncio
import copy
import json
import logging
import os
import shutil
import time

logger = logging.getLogger(__name__)

STATE_FILE = "data/state.json"

DEFAULTS = {
    "afk": {},
    "afk_config": {"cooldown": 10, "reply_mentions": True, "reply_dms": True},
    "reactions": {},
    "auto": {
        "auto_responses": {},
        "auto_mess_config": {"active": False, "mode": "time", "value": 60},
        "message_pool": [
            "Hello from auto message!",
            "Thank you for messaging.",
            "Have a great day."
        ]
    }
}


def _deep_merge(loaded: dict, defaults: dict) -> dict:
    """Đệ quy bổ sung key thiếu/sai type từ defaults; giá trị đã có trong loaded được giữ nguyên."""
    for key, default_value in defaults.items():
        if key not in loaded:
            loaded[key] = copy.deepcopy(default_value)
            continue
        # None thay bằng default (tránh JSON có "auto": null crash downstream)
        if loaded[key] is None:
            loaded[key] = copy.deepcopy(default_value)
            continue
        # bool/int phải đối xứng tuyệt đối (bool là subclass của int — không lẫn lộn)
        if isinstance(default_value, bool) != isinstance(loaded[key], bool):
            loaded[key] = copy.deepcopy(default_value)
        elif not isinstance(loaded[key], type(default_value)):
            loaded[key] = copy.deepcopy(default_value)
        elif isinstance(default_value, dict) and isinstance(loaded[key], dict):
            _deep_merge(loaded[key], default_value)
    return loaded


def load_state(path, defaults):
    """Load JSON state file, deep-merging any missing sections/subkeys from defaults.

    File hỏng (cắt/ngắt điện) sẽ được rename thành <path>.corrupt-<ts> để giữ dữ liệu
    gốc thay vì bị defaults ghi đè vĩnh viễn ở lần save kế tiếp.
    Thử load .bak khi file chính missing hoặc corrupt.
    """
    fallback = copy.deepcopy(defaults)
    bak = path + ".bak"
    if not os.path.exists(path):
        # Thử load .bak khi file chính missing (xóa nhầm / crash giữa replace)
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = _deep_merge(loaded, defaults)
                    logger.warning(f"File {path} missing — khôi phục từ {bak}")
                    # Best-effort: vá lại file chính
                    try:
                        save_state(path, data)
                    except Exception:
                        pass
                    return data
            except Exception as e:
                logger.warning(f"Load {bak} fail: {e}")
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            return _deep_merge(loaded, defaults)
        # JSON hợp lệ nhưng không phải dict (ví dụ "[]" hoặc số) — cũng coi là hỏng
        raise ValueError(f"state không phải JSON object: {type(loaded).__name__}")
    except Exception as e:
        # Thử .bak trước khi rename corrupt
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    bak_data = json.load(f)
                if isinstance(bak_data, dict):
                    logger.warning(f"File {path} hỏng ({e}) — dùng {bak}")
                    # Rename file hỏng TRƯỚC khi return để lần sau không load lại file hỏng
                    ts = int(time.time())
                    try:
                        os.replace(path, f"{path}.corrupt-{ts}")
                    except OSError:
                        pass
                    return _deep_merge(bak_data, defaults)
            except Exception as be:
                logger.warning(f"{bak} cũng hỏng ({be})")
        ts = int(time.time())
        corrupt_name = f"{path}.corrupt-{ts}"
        try:
            os.replace(path, corrupt_name)
            logger.error(f"File {path} hỏng ({e}) — đã đổi tên thành {corrupt_name}, dùng defaults cho lần chạy này")
        except OSError as rename_err:
            logger.error(f"File {path} hỏng ({e}) và không rename được ({rename_err}) — dùng defaults")
    return fallback


_locks: dict[str, tuple[asyncio.Lock, object]] = {}


def _get_lock(path: str) -> asyncio.Lock:
    """Lock per-file, gắn theo event loop hiện tại.

    bot.run() tạo event loop mới sau mỗi lần crash-restart — lock của loop cũ
    sẽ raise 'bound to a different event loop' nên phải discard và tạo lại.
    """
    loop = asyncio.get_running_loop()
    entry = _locks.get(path)
    if entry is not None and entry[1] is not loop:
        logger.warning(f"Event loop mới phát hiện — tạo lại lock cho {path}")
        entry = None
    if entry is None:
        entry = (asyncio.Lock(), loop)
        _locks[path] = entry
    return entry[0]


async def update_state(path, defaults, mutator):
    """Read-modify-write state file dưới lock per-file — tránh lost update khi nhiều coroutine ghi cùng lúc."""
    async with _get_lock(path):
        data = load_state(path, defaults)
        result = mutator(data)
        if not save_state(path, data):
            logger.error(f"update_state: ghi {path} THẤT BẠI — thay đổi chỉ nằm trong bộ nhớ")
        return result


def save_state(path, data):
    """Save JSON state file atomically (tmp + replace) để không bao giờ mất data khi crash.

    Backup .bak trước khi replace để cứu dữ liệu nếu mất điện giữa chừng.
    """
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = f"{path}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        # Backup .bak trước replace — cứu data khi crash giữa ghi
        if path.endswith(".json") and os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak")
                # fsync .bak — đảm bảo backup durable
                try:
                    with open(path + ".bak", "rb") as bf:
                        os.fsync(bf.fileno())
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Backup .bak thất bại cho {path}: {e}")
        os.replace(tmp, path)
        # fsync directory — đảm bảo entry durable sau mất điện
        try:
            dir_fd = os.open(d or ".", os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (AttributeError, OSError):
            # Windows không có O_DIRECTORY — bỏ qua
            pass
        return True
    except Exception as e:
        logger.error(f"Lỗi ghi {path}: {e}")
        return False


def _migrate_general_state():
    """Merge afk_status.json + triggers.json + message_sent.txt vào state.json."""
    if os.path.exists(STATE_FILE):
        return

    state = load_state(STATE_FILE, DEFAULTS)

    # afk_status.json
    if os.path.exists("data/afk_status.json"):
        try:
            with open("data/afk_status.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                state["afk"] = loaded
        except Exception as e:
            logger.error(f"Lỗi migrate afk_status.json: {e}")

    # triggers.json -> auto
    if os.path.exists("data/triggers.json"):
        try:
            with open("data/triggers.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for key in ("auto_responses", "auto_messages"):
                    if isinstance(loaded.get(key), dict):
                        state["auto"][key] = loaded[key]
                if isinstance(loaded.get("auto_mess_config"), dict):
                    state["auto"]["auto_mess_config"] = loaded["auto_mess_config"]
        except Exception as e:
            logger.error(f"Lỗi migrate triggers.json: {e}")

    # message_sent.txt -> message_pool
    if os.path.exists("data/message_sent.txt"):
        try:
            with open("data/message_sent.txt", "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            if lines:
                state["auto"]["message_pool"] = lines
        except Exception as e:
            logger.error(f"Lỗi migrate message_sent.txt: {e}")

    if save_state(STATE_FILE, state):
        for f in ("data/afk_status.json", "data/triggers.json", "data/message_sent.txt"):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception as e:
                logger.error(f"Lỗi xóa {f}: {e}")
        logger.info("✅ Migrated afk_status/triggers/message_sent.txt -> data/state.json")


def migrate_legacy():
    """One-time migration of legacy data files vào state.json."""
    os.makedirs("data", exist_ok=True)
    _migrate_general_state()

    # Dead file, delete directly
    for dead in ("data/message_afk.json", "data/permissions.json"):
        try:
            if os.path.exists(dead):
                os.remove(dead)
        except Exception as e:
            logger.error(f"Lỗi xóa {dead}: {e}")
