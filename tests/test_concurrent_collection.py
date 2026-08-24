from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from scripts import fetch_stats


TIMESTAMP = "2026-08-24T00:00:00Z"


def make_instance(host: str) -> fetch_stats.Instance:
    return fetch_stats.Instance(host, host, f"https://{host}", "mastodon")


def make_record(
    host: str,
    *,
    good: bool,
    consecutive_failures: int = 0,
) -> Dict[str, Any]:
    return {
        "host": host,
        "verified_activitypub": good,
        "software": {"name": "mastodon", "version": "test"} if good else {},
        "open_registrations": True if good else None,
        "users_total": 1 if good else None,
        "users_active_month": 1 if good else None,
        "statuses": 1 if good else None,
        "languages_detected": ["en"] if good else [],
        "fetched_at": TIMESTAMP,
        "consecutive_failures": consecutive_failures,
    }


def make_result(
    instance: fetch_stats.Instance,
    *,
    good: bool = True,
    peers: set[str] | None = None,
) -> fetch_stats.FetchResult:
    return fetch_stats.FetchResult(
        instance=instance,
        record=make_record(instance.host, good=good),
        errors=[] if good else ["timeout"],
        peers=peers or set(),
    )


def monitored_entries(instances: list[fetch_stats.Instance]):
    return {
        instance.host: {
            "host": instance.host,
            "url": instance.url,
            "source": "peer",
            "platform": instance.platform,
        }
        for instance in instances
    }


def make_state(
    instances: list[fetch_stats.Instance],
    *,
    ok_map: Dict[str, Dict[str, Any]] | None = None,
    bad_map: Dict[str, Dict[str, Any]] | None = None,
    candidate_mode: bool = False,
    discover_peers: bool = False,
) -> fetch_stats.CollectionState:
    return fetch_stats.CollectionState(
        ok_map=ok_map or {},
        bad_map=bad_map or {},
        monitored=monitored_entries(instances),
        aliases={},
        manual_overrides={},
        candidate_mode=candidate_mode,
        discover_peers=discover_peers,
        total=len(instances),
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def prepare_data(
    data_dir: Path,
    instances: list[fetch_stats.Instance],
    *,
    ok: list[dict[str, Any]] | None = None,
) -> None:
    data_dir.mkdir()
    write_json(data_dir / "instances.json", [])
    write_json(data_dir / "stats.ok.json", ok or [])
    write_json(data_dir / "stats.bad.json", [])
    write_json(data_dir / "host_aliases.json", {})
    write_json(data_dir / "manual_overrides.json", {})
    write_json(
        data_dir / "monitored_instances.json",
        list(monitored_entries(instances).values()),
    )


def test_bounded_workers_fetch_each_host_once_and_apply_on_main_thread() -> None:
    instances = [make_instance(f"host-{index}.example") for index in range(40)]
    calls: list[str] = []
    worker_threads: set[int] = set()
    callback_threads: set[int] = set()
    lock = threading.Lock()
    main_thread = threading.get_ident()

    def fetcher(instance: fetch_stats.Instance, timestamp: str):
        with lock:
            calls.append(instance.host)
            worker_threads.add(threading.get_ident())
        time.sleep(0.002)
        return make_result(instance)

    def on_result(result: fetch_stats.FetchResult) -> None:
        callback_threads.add(threading.get_ident())

    fetch_stats.run_bounded_fetches(
        instances,
        TIMESTAMP,
        on_result,
        workers=8,
        fetcher=fetcher,
    )

    assert len(calls) == len(instances)
    assert set(calls) == {instance.host for instance in instances}
    assert callback_threads == {main_thread}
    assert main_thread not in worker_threads
    assert 1 < len(worker_threads) <= 8


def test_out_of_order_completion_preserves_health_transitions() -> None:
    slow_good = make_instance("good.example")
    fast_failure = make_instance("failing.example")
    instances = [slow_good, fast_failure]
    state = make_state(
        instances,
        ok_map={
            slow_good.host: make_record(slow_good.host, good=True),
            fast_failure.host: make_record(
                fast_failure.host, good=True, consecutive_failures=2
            ),
        },
    )
    completion_order: list[str] = []

    def fetcher(instance: fetch_stats.Instance, timestamp: str):
        if instance.host == slow_good.host:
            time.sleep(0.03)
            return make_result(instance, good=True)
        time.sleep(0.001)
        return make_result(instance, good=False)

    def on_result(result: fetch_stats.FetchResult) -> None:
        completion_order.append(result.instance.host)
        fetch_stats.apply_fetch_result(state, result)

    fetch_stats.run_bounded_fetches(
        instances,
        TIMESTAMP,
        on_result,
        workers=2,
        fetcher=fetcher,
    )

    assert completion_order == ["failing.example", "good.example"]
    assert set(state.ok_map) == {"good.example"}
    assert set(state.bad_map) == {"failing.example"}
    assert state.bad_map["failing.example"]["consecutive_failures"] == 3
    assert set(state.monitored) == {"failing.example", "good.example"}


def test_workers_one_still_processes_all_hosts() -> None:
    instances = [make_instance(f"single-{index}.example") for index in range(4)]
    completed: list[str] = []

    fetch_stats.run_bounded_fetches(
        instances,
        TIMESTAMP,
        lambda result: completed.append(result.instance.host),
        workers=1,
        fetcher=lambda instance, timestamp: make_result(instance),
    )

    assert sorted(completed) == sorted(instance.host for instance in instances)
    assert len(completed) == len(instances)


def test_pipeline_deduplicates_duplicate_host_submissions() -> None:
    duplicate = make_instance("duplicate.example")
    calls = 0

    def fetcher(instance: fetch_stats.Instance, timestamp: str):
        nonlocal calls
        calls += 1
        return make_result(instance)

    fetch_stats.run_bounded_fetches(
        [duplicate, duplicate, duplicate],
        TIMESTAMP,
        lambda result: None,
        workers=3,
        fetcher=fetcher,
    )

    assert calls == 1


def test_checkpoint_interval_and_final_partial_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = make_state([make_instance(f"host-{index}.example") for index in range(5)])
    saved_at: list[int] = []

    monkeypatch.setattr(
        fetch_stats,
        "save_stats_pair_atomic",
        lambda ok, bad, aliases: saved_at.append(state.processed),
    )

    for processed in range(1, 6):
        state.processed = processed
        if state.processed - state.last_checkpoint >= 2:
            fetch_stats.checkpoint_collection(state)
    fetch_stats.checkpoint_collection(state, force=True)

    assert saved_at == [2, 4, 5]


def test_keyboard_interrupt_saves_completed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    instances = [make_instance("done.example"), make_instance("pending.example")]
    prepare_data(data_dir, instances)

    def interrupt_after_one(
        queued,
        timestamp,
        on_result,
        *,
        workers,
        **kwargs,
    ):
        on_result(make_result(queued[0]))
        raise KeyboardInterrupt

    monkeypatch.setattr(fetch_stats, "run_bounded_fetches", interrupt_after_one)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fetch_stats.py",
            "--data-dir",
            str(data_dir),
            "--workers",
            "2",
            "--checkpoint-every",
            "100",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        fetch_stats.main()

    assert exit_info.value.code == 130
    saved_ok = json.loads((data_dir / "stats.ok.json").read_text())
    assert [record["host"] for record in saved_ok] == ["done.example"]
    registry = json.loads((data_dir / "monitored_instances.json").read_text())
    assert {entry["host"] for entry in registry} == {
        "done.example",
        "pending.example",
    }


def test_concurrent_peer_merge_and_checked_hosts_loaded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    instances = [make_instance(f"seed-{index}.example") for index in range(3)]
    prepare_data(data_dir, instances)
    checked_calls = 0

    def fake_process(
        instance: fetch_stats.Instance,
        timestamp: str,
        *,
        discover_peers: bool = False,
    ):
        assert discover_peers is True
        return (
            make_record(instance.host, good=True),
            [],
            {"shared-peer.example", f"peer-{instance.host}"},
        )

    original_load_checked = fetch_stats.load_checked_hosts

    def counted_load_checked():
        nonlocal checked_calls
        checked_calls += 1
        return original_load_checked()

    monkeypatch.setattr(fetch_stats, "process_instance", fake_process)
    monkeypatch.setattr(fetch_stats, "load_checked_hosts", counted_load_checked)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fetch_stats.py",
            "--data-dir",
            str(data_dir),
            "--discover-peers",
            "--workers",
            "3",
        ],
    )

    fetch_stats.main()

    suggestions = json.loads((data_dir / "peer_suggestions.json").read_text())
    assert checked_calls == 1
    assert suggestions == [
        "peer-seed-0.example",
        "peer-seed-1.example",
        "peer-seed-2.example",
        "shared-peer.example",
    ]


def test_alias_result_keeps_registry_canonical_and_ok_subset_monitored() -> None:
    alias = make_instance("social.example")
    state = make_state([alias])
    result = make_result(alias)
    result.record["redirected_from"] = "social.example"
    result.record["host"] = "mastodon.social.example"

    fetch_stats.apply_fetch_result(state, result)

    assert state.aliases == {"social.example": "mastodon.social.example"}
    assert set(state.monitored) == {"mastodon.social.example"}
    assert set(state.ok_map) <= set(state.monitored)


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--workers", "0"),
        ("--workers", str(fetch_stats.MAX_WORKERS + 1)),
        ("--checkpoint-every", "0"),
        ("--checkpoint-every", "not-a-number"),
    ],
)
def test_invalid_concurrency_cli_values_are_rejected(
    option: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["fetch_stats.py", option, value])

    with pytest.raises(SystemExit) as exit_info:
        fetch_stats.parse_args()

    assert exit_info.value.code == 2
