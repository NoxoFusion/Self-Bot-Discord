from __future__ import annotations

import copy
import json
import logging

import pytest

from dashboard.backend.state_store import DEFAULT_STATE, StateStore

pytestmark = pytest.mark.asyncio


async def test_defaults_when_file_is_missing(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    assert await store.load() == DEFAULT_STATE
    assert not path.exists()


async def test_automation_defaults_to_disabled(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    loaded = await store.load()

    assert loaded["automation"]["enabled"] is False


async def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    data = copy.deepcopy(DEFAULT_STATE)
    data["afk"] = {
        **DEFAULT_STATE["afk"],
        "enabled": True,
        "reason": "lunch",
    }
    data["automation"]["triggers"] = [{"keyword": "hi", "reply": "hello"}]

    saved = await store.save(data)
    assert saved == data
    assert await store.load() == data
    assert json.loads(path.read_text(encoding="utf-8")) == data


async def test_missing_keys_are_deep_merged_from_defaults(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    saved = await store.save({"afk": {"enabled": True}})

    assert saved["afk"] == {
        "enabled": True,
        "reason": "",
        "cooldown": 10,
        "reply_mentions": True,
        "reply_dms": True,
    }
    assert saved["automation"] == DEFAULT_STATE["automation"]
    assert saved["reactions"] == DEFAULT_STATE["reactions"]


async def test_afk_default_shape(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    loaded = await store.load()

    assert loaded["afk"] == {
        "enabled": False,
        "reason": "",
        "cooldown": 10,
        "reply_mentions": True,
        "reply_dms": True,
    }


async def test_corrupt_file_returns_defaults_and_warns(tmp_path, caplog):
    path = tmp_path / "runtime_state.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = StateStore(path)

    with caplog.at_level(logging.WARNING):
        loaded = await store.load()

    assert loaded == DEFAULT_STATE
    assert any(
        "corrupt" in record.message.lower() for record in caplog.records
    )


async def test_save_writes_atomically_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    await store.save(DEFAULT_STATE)

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULT_STATE
    assert [entry.name for entry in tmp_path.iterdir()] == [path.name]


async def test_update_mutates_and_persists(tmp_path):
    path = tmp_path / "runtime_state.json"
    store = StateStore(path)

    def mutator(state):
        state["reactions"]["enabled"] = True
        return state

    updated = await store.update(mutator)

    assert updated["reactions"]["enabled"] is True
    assert (await store.load())["reactions"]["enabled"] is True
