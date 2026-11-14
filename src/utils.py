"""Helpers dùng chung cho các cog."""

import discord


async def try_delete(message: discord.Message) -> None:
    """Xóa tin nhắn lệnh, lặng lẽ bỏ qua mọi lỗi HTTP (đã bị xóa/thiếu quyền)."""
    try:
        await message.delete()
    except discord.HTTPException:
        pass


# Chỉ waiter xác nhận MỚI NHẤT trên một channel được nhận "confirm"; nếu không,
# hai lệnh cùng chờ trong một channel sẽ cùng chạy từ một tin nhắn duy nhất.
_CONFIRM_TOKENS: dict[int, object] = {}


def begin_confirm(channel_id):
    token = object()
    _CONFIRM_TOKENS[channel_id] = token
    return token


def is_current_confirm(channel_id, token):
    return _CONFIRM_TOKENS.get(channel_id) is token


def end_confirm(channel_id, token):
    if _CONFIRM_TOKENS.get(channel_id) is token:
        _CONFIRM_TOKENS.pop(channel_id, None)
