from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from scripts import fetch_stats


def make_record(
    host: str,
    *,
    good: bool,
    fetched_at: str = "2026-08-24T00:00:00Z",
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
        "fetched_at": fetched_at,
        "consecutive_failures": consecutive_failures,
    }


def apply(
    record: Dict[str, Any],
    bucket: str,
    ok_map: Dict[str, Dict[str, Any]],
    bad_map: Dict[str, Dict[str, Any]],
    aliases: Optional[Dict[str, str]] = None,
):
    return fetch_stats.apply_health_transition(
        record,
        bucket,
        ok_map,
        bad_map,
        aliases or {},
        failure_reason="test failure",
    )


def test_good_refresh_remains_only_in_ok() -> None:
    old = make_record("a.example", good=True)
    ok_map = {"a.example": old}
    bad_map = {"a.example": make_record("a.example", good=False)}

    state, _, _, failures = apply(
        make_record("a.example", good=True, fetched_at="2026-08-25T00:00:00Z"),
        "good",
        ok_map,
        bad_map,
    )

    assert state == "good"
    assert failures == 0
    assert set(ok_map) == {"a.example"}
    assert bad_map == {}


def test_bad_host_recovers_to_ok() -> None:
    ok_map: Dict[str, Dict[str, Any]] = {}
    bad_map = {"a.example": make_record("a.example", good=False, consecutive_failures=3)}

    apply(make_record("a.example", good=True), "good", ok_map, bad_map)

    assert set(ok_map) == {"a.example"}
    assert ok_map["a.example"]["consecutive_failures"] == 0
    assert bad_map == {}


def test_first_failure_retains_last_known_good_record() -> None:
    ok_map = {"a.example": make_record("a.example", good=True)}
    bad_map: Dict[str, Dict[str, Any]] = {}

    state, _, _, failures = apply(
        make_record("a.example", good=False, fetched_at="2026-08-25T00:00:00Z"),
        "bad",
        ok_map,
        bad_map,
    )

    assert state == "transient_failure"
    assert failures == 1
    assert ok_map["a.example"]["verified_activitypub"] is True
    assert ok_map["a.example"]["consecutive_failures"] == 1
    assert ok_map["a.example"]["last_failure_at"] == "2026-08-25T00:00:00Z"
    assert bad_map == {}


def test_consecutive_failures_accumulate_then_move_ok_to_bad() -> None:
    ok_map = {"a.example": make_record("a.example", good=True)}
    bad_map: Dict[str, Dict[str, Any]] = {}

    for attempt in range(1, fetch_stats.FAILURE_THRESHOLD + 1):
        state, _, _, failures = apply(
            make_record(
                "a.example",
                good=False,
                fetched_at=f"2026-08-{24 + attempt:02d}T00:00:00Z",
            ),
            "bad",
            ok_map,
            bad_map,
        )
        assert failures == attempt

    assert state == "bad"
    assert ok_map == {}
    assert set(bad_map) == {"a.example"}
    assert bad_map["a.example"]["consecutive_failures"] == fetch_stats.FAILURE_THRESHOLD


def test_success_resets_transient_failure_state() -> None:
    previous = make_record("a.example", good=True, consecutive_failures=2)
    previous["last_failure_at"] = "2026-08-25T00:00:00Z"
    previous["last_failure_reason"] = "timeout"
    ok_map = {"a.example": previous}
    bad_map: Dict[str, Dict[str, Any]] = {}

    apply(make_record("a.example", good=True), "good", ok_map, bad_map)

    assert ok_map["a.example"]["consecutive_failures"] == 0
    assert "last_failure_at" not in ok_map["a.example"]
    assert "last_failure_reason" not in ok_map["a.example"]
    assert bad_map == {}


def test_alias_variants_are_collapsed_to_one_canonical_state() -> None:
    aliases = {"a.example": "canonical.example"}
    ok_map = {"a.example": make_record("a.example", good=True)}
    bad_map = {
        "canonical.example": make_record("canonical.example", good=False)
    }

    apply(
        make_record("a.example", good=True),
        "good",
        ok_map,
        bad_map,
        aliases,
    )

    assert set(ok_map) == {"canonical.example"}
    assert bad_map == {}


def test_atomic_save_writes_disjoint_host_sets(tmp_path: Path) -> None:
    fetch_stats.configure_data_dir(tmp_path)
    ok_map = {"a.example": make_record("a.example", good=True)}
    bad_map = {"b.example": make_record("b.example", good=False)}
    apply(make_record("a.example", good=False), "bad", ok_map, bad_map)

    fetch_stats.save_stats_pair_atomic(ok_map, bad_map)

    saved_ok = json.loads(fetch_stats.STATS_OK_PATH.read_text())
    saved_bad = json.loads(fetch_stats.STATS_BAD_PATH.read_text())
    ok_hosts = {record["host"] for record in saved_ok}
    bad_hosts = {record["host"] for record in saved_bad}
    assert ok_hosts.isdisjoint(bad_hosts)


def test_atomic_save_repairs_existing_alias_overlap(tmp_path: Path) -> None:
    fetch_stats.configure_data_dir(tmp_path)
    fetch_stats.ALIASES_PATH.write_text(
        json.dumps({"a.example": "canonical.example"}), encoding="utf-8"
    )
    ok_map = {"a.example": make_record("a.example", good=True)}
    bad_record = make_record(
        "canonical.example",
        good=False,
        consecutive_failures=fetch_stats.FAILURE_THRESHOLD,
    )
    bad_map = {"canonical.example": bad_record}

    fetch_stats.save_stats_pair_atomic(ok_map, bad_map)

    saved_ok = json.loads(fetch_stats.STATS_OK_PATH.read_text())
    saved_bad = json.loads(fetch_stats.STATS_BAD_PATH.read_text())
    assert saved_ok == []
    assert [record["host"] for record in saved_bad] == ["canonical.example"]
