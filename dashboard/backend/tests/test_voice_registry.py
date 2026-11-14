from __future__ import annotations

import pytest

from dashboard.backend import voice_api
from dashboard.backend.voice_api import register_voice_api
from src import voice_actions
from src.voice_actions import dispatch_extra


def test_register_voice_api_calls_each_module_register_once(monkeypatch):
    calls = []

    class FakeModule:
        def __init__(self, name: str) -> None:
            self.__name__ = name

        def register(self, app) -> None:
            calls.append((self.__name__, app))

    modules = [FakeModule("fake_one"), FakeModule("fake_two")]
    fake_app = object()

    monkeypatch.setattr(voice_api, "_iter_modules", lambda: modules)

    register_voice_api(fake_app)

    assert calls == [("fake_one", fake_app), ("fake_two", fake_app)]


@pytest.mark.asyncio
async def test_dispatch_extra_awaits_matching_handler(monkeypatch):
    handled = []

    async def handle(action, command, cog) -> None:
        handled.append((action, command, cog))

    monkeypatch.setattr(voice_actions, "_HANDLERS", {"extra": handle})

    command = {"action": "extra", "value": 1}
    cog = object()

    assert await dispatch_extra("extra", command, cog) is True
    assert handled == [("extra", command, cog)]


@pytest.mark.asyncio
async def test_dispatch_extra_returns_false_for_unknown_action(monkeypatch):
    monkeypatch.setattr(voice_actions, "_HANDLERS", {})

    assert await dispatch_extra("unknown", {}, object()) is False


@pytest.mark.asyncio
async def test_dispatch_extra_swallows_handler_errors(monkeypatch):
    async def handle(action, command, cog) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(voice_actions, "_HANDLERS", {"broken": handle})

    assert await dispatch_extra("broken", {}, object()) is True


def test_protected_paths_collects_module_declarations(monkeypatch):
    class FakeModule:
        PROTECTED_PATHS = {"/api/v1/voice/state"}
        PROTECTED_MUTATION_PATHS = {"/api/v1/voice/state"}

    monkeypatch.setattr(voice_api, "_iter_modules", lambda: [FakeModule()])

    assert voice_api.protected_paths() == {"/api/v1/voice/state"}
    assert voice_api.protected_mutation_paths() == {"/api/v1/voice/state"}
