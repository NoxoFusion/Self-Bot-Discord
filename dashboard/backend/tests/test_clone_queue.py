from __future__ import annotations

import json
import time

from dashboard.backend.clone_queue import CloneCommandQueue, CloneResultStore


def test_clone_command_queue_writes_one_spool_file_per_command(tmp_path):
    path = tmp_path / "clone_commands.json"
    queue = CloneCommandQueue(path)

    first = {"request_id": "a", "source_id": "1", "target_id": "2"}
    second = {"request_id": "b", "source_id": "3", "target_id": "4"}
    queue.enqueue(first)
    queue.enqueue(second)

    files = sorted((tmp_path / "clone_commands.spool").glob("*.json"))
    assert len(files) == 2
    commands = [json.loads(item.read_text(encoding="utf-8")) for item in files]
    assert sorted(commands, key=lambda command: command["request_id"]) == [
        first,
        second,
    ]
    assert not path.exists()


def test_clone_command_queue_two_enqueues_create_distinct_files(tmp_path):
    path = tmp_path / "clone_commands.json"
    queue = CloneCommandQueue(path)
    spool = tmp_path / "clone_commands.spool"

    queue.enqueue({"request_id": "a", "source_id": "1", "target_id": "2"})
    first_files = {item.name for item in spool.glob("*.json")}

    queue.enqueue({"request_id": "b", "source_id": "3", "target_id": "4"})
    second_files = {item.name for item in spool.glob("*.json")}

    assert len(first_files) == 1
    assert len(second_files) == 2
    assert first_files < second_files
    assert not path.exists()


def test_clone_result_store_roundtrip(tmp_path):
    path = tmp_path / "clone_results.json"
    store = CloneResultStore(path)

    store.write("request-1", "running")
    store.write("request-1", "success", "done")
    store.write("request-2", "error", "failed")

    assert store.read("request-1")["status"] == "success"
    assert store.read("request-1")["message"] == "done"
    assert store.read("request-2")["status"] == "error"
    assert store.read("missing") is None


def test_clone_result_store_prunes_entries_older_than_24_hours(tmp_path):
    path = tmp_path / "clone_results.json"
    now = time.time()
    path.write_text(
        json.dumps(
            {
                "old": {
                    "status": "success",
                    "message": "",
                    "updated_at": now - 25 * 60 * 60,
                },
                "new": {
                    "status": "running",
                    "message": "",
                    "updated_at": now,
                },
                "untimed": {"status": "success", "message": ""},
            }
        ),
        encoding="utf-8",
    )
    store = CloneResultStore(path)

    store.write("written", "success", "done")

    assert store.read("old") is None
    assert store.read("new")["status"] == "running"
    assert store.read("untimed")["status"] == "success"
    assert store.read("written")["status"] == "success"
