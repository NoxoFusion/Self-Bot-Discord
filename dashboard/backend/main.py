"""Run the local dashboard API server.

Usage from the repository root::

    python dashboard/backend/main.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from aiohttp import web

try:  # imported as a package (``python -m dashboard.backend.main``)
    from .app import create_app
    from .auth import generate_pairing_code
    from .bot_adapter import LiveBotAdapter
    from .clone_queue import CloneCommandQueue, CloneResultStore
    from .config import (
        delete_root_voice_token,
        load_config,
        load_root_bot_token,
        load_root_voice_tokens,
    )
    from .discord_profile import DiscordProfileService
    from .emoji_queue import EmojiCommandQueue, EmojiResultStore
    from .state_store import StateStore
    from .voice import (
        SoundboardService,
        TokenProfileStore,
        VoiceCommandQueue,
        VoiceTokenService,
        read_voice_state,
    )
except ImportError:  # executed directly as ``python dashboard/backend/main.py``
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from dashboard.backend.app import create_app
    from dashboard.backend.auth import generate_pairing_code
    from dashboard.backend.bot_adapter import LiveBotAdapter
    from dashboard.backend.clone_queue import (
        CloneCommandQueue,
        CloneResultStore,
    )
    from dashboard.backend.config import (
        delete_root_voice_token,
        load_config,
        load_root_bot_token,
        load_root_voice_tokens,
    )
    from dashboard.backend.discord_profile import DiscordProfileService
    from dashboard.backend.emoji_queue import (
        EmojiCommandQueue,
        EmojiResultStore,
    )
    from dashboard.backend.state_store import StateStore
    from dashboard.backend.voice import (
        SoundboardService,
        TokenProfileStore,
        VoiceCommandQueue,
        VoiceTokenService,
        read_voice_state,
    )

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    backend_dir = Path(__file__).resolve().parent
    state_store = StateStore(backend_dir / "runtime_state.json")
    pairing_code = generate_pairing_code()
    profile_service = DiscordProfileService(
        config.get("bot_token") or load_root_bot_token()
    )
    voice_token_loader = load_root_voice_tokens
    profile_store = TokenProfileStore(voice_token_loader)
    voice_command_queue = VoiceCommandQueue(backend_dir / "voice_commands.json")

    def _purge_expired_voice_tokens(indices: list[int]) -> None:
        deleted = False
        for index in sorted(indices, reverse=True):
            if delete_root_voice_token(index):
                profile_store.forget(index)
                deleted = True
        if deleted:
            voice_command_queue.enqueue({"action": "reload"})

    voice_service = VoiceTokenService(
        voice_token_loader,
        on_unauthorized=_purge_expired_voice_tokens,
        state_reader=lambda: read_voice_state(
            backend_dir / "voice_state.json"
        ),
        ttl=5.0,
    )
    soundboard_service = SoundboardService(voice_token_loader)
    clone_queue = CloneCommandQueue(backend_dir / "clone_commands.json")
    clone_results = CloneResultStore(backend_dir / "clone_results.json")
    emoji_queue = EmojiCommandQueue(backend_dir / "emoji_commands.json")
    emoji_results = EmojiResultStore(backend_dir / "emoji_results.json")

    app = create_app(
        config=config,
        state_store=state_store,
        pairing_code=pairing_code,
        adapter=LiveBotAdapter(backend_dir / "bot_status.json"),
        profile_service=profile_service,
        voice_service=voice_service,
        token_profile_store=profile_store,
        soundboard_service=soundboard_service,
        voice_command_queue=voice_command_queue,
        voice_state_path=backend_dir / "voice_state.json",
        clone_queue=clone_queue,
        clone_results=clone_results,
        emoji_queue=emoji_queue,
        emoji_results=emoji_results,
    )

    print(f"[dashboard] Pairing code: {pairing_code}", flush=True)
    logger.info(
        "Live bot adapter enabled — status comes from %s",
        backend_dir / "bot_status.json",
    )
    if config["api_host"] not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            "SECURITY: dashboard api_host is %r, which is not loopback; "
            "the dashboard is exposed beyond this machine.",
            config["api_host"],
        )

    web.run_app(
        app,
        host=config["api_host"],
        port=config["api_port"],
        print=None,
    )


if __name__ == "__main__":
    main()
