from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from scripts import fetch_stats


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


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
        "fetched_at": "2026-08-24T00:00:00Z",
        "consecutive_failures": consecutive_failures,
    }


def prepare_data(
    data_dir: Path,
    *,
    instances: list[object],
    ok: list[object],
    bad: list[object] | None = None,
    monitored: list[object] | None = None,
    aliases: dict[str, str] | None = None,
) -> None:
    data_dir.mkdir()
    write_json(data_dir / "instances.json", instances)
    write_json(data_dir / "stats.ok.json", ok)
    write_json(data_dir / "stats.bad.json", bad or [])
    write_json(data_dir / "host_aliases.json", aliases or {})
    write_json(data_dir / "manual_overrides.json", {})
    if monitored is not None:
        write_json(data_dir / "monitored_instances.json", monitored)


def good_result(instance: fetch_stats.Instance, timestamp: str):
    record = make_record(instance.host, good=True)
    record["fetched_at"] = timestamp
    return record, [], set()


def test_missing_registry_bootstraps_seed_and_existing_ok(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        instances=[{"name": "Seed", "url": "https://seed.example"}],
        ok=[make_record("discovered.example", good=True)],
    )
    fetch_stats.configure_data_dir(data_dir)

    seeds = list(fetch_stats.load_instances(fetch_stats.INSTANCES_PATH))
    ok_map, _ = fetch_stats.load_existing_stats_maps()
    registry, changed = fetch_stats.prepare_monitored_registry(seeds, ok_map, {})

    assert changed is True
    assert set(registry) == {"seed.example", "discovered.example"}
    assert registry["seed.example"]["source"] == "seed"
    assert registry["discovered.example"]["source"] == "legacy"


def test_default_run_checks_discovered_ok_and_deduplicates_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        instances=[{"name": "Seed", "url": "https://seed.example"}],
        ok=[
            make_record("seed.example", good=True),
            make_record("discovered.example", good=True),
        ],
        monitored=[
            {
                "host": "seed.example",
                "url": "https://seed.example",
                "source": "seed",
            },
            {
                "host": "discovered.example",
                "url": "https://discovered.example",
                "source": "peer",
            },
        ],
    )
    processed: list[str] = []

    def fake_process(instance: fetch_stats.Instance, timestamp: str):
        processed.append(instance.host)
        return good_result(instance, timestamp)

    monkeypatch.setattr(fetch_stats, "process_instance", fake_process)
    monkeypatch.setattr("sys.argv", ["fetch_stats.py", "--data-dir", str(data_dir)])

    fetch_stats.main()

    assert processed == ["discovered.example", "seed.example"]


def test_threshold_failure_removes_display_state_but_keeps_monitoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    previous = make_record("discovered.example", good=True, consecutive_failures=2)
    prepare_data(
        data_dir,
        instances=[],
        ok=[previous],
        monitored=[
            {
                "host": "discovered.example",
                "url": "https://discovered.example",
                "source": "peer",
            }
        ],
    )

    def fail(instance: fetch_stats.Instance, timestamp: str):
        record = make_record(instance.host, good=False)
        record["fetched_at"] = timestamp
        return record, ["timeout"], set()

    monkeypatch.setattr(fetch_stats, "process_instance", fail)
    monkeypatch.setattr("sys.argv", ["fetch_stats.py", "--data-dir", str(data_dir)])

    fetch_stats.main()

    assert json.loads((data_dir / "stats.ok.json").read_text()) == []
    assert json.loads((data_dir / "stats.bad.json").read_text())[0][
        "consecutive_failures"
    ] == fetch_stats.FAILURE_THRESHOLD
    registry = json.loads((data_dir / "monitored_instances.json").read_text())
    assert [entry["host"] for entry in registry] == ["discovered.example"]


def test_bad_monitored_host_is_rechecked_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        instances=[],
        ok=[],
        bad=[
            make_record(
                "recovered.example",
                good=False,
                consecutive_failures=fetch_stats.FAILURE_THRESHOLD,
            )
        ],
        monitored=[
            {
                "host": "recovered.example",
                "url": "https://recovered.example",
                "source": "peer",
            }
        ],
    )
    processed: list[str] = []

    def recover(instance: fetch_stats.Instance, timestamp: str):
        processed.append(instance.host)
        return good_result(instance, timestamp)

    monkeypatch.setattr(fetch_stats, "process_instance", recover)
    monkeypatch.setattr("sys.argv", ["fetch_stats.py", "--data-dir", str(data_dir)])

    fetch_stats.main()

    assert processed == ["recovered.example"]
    assert json.loads((data_dir / "stats.bad.json").read_text()) == []
    assert json.loads((data_dir / "stats.ok.json").read_text())[0]["host"] == (
        "recovered.example"
    )


def test_successful_candidate_joins_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    prepare_data(data_dir, instances=[], ok=[], monitored=[])
    candidates = data_dir / "filtered_peers.json"
    write_json(candidates, ["candidate.example"])
    monkeypatch.setattr(fetch_stats, "process_instance", good_result)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fetch_stats.py",
            "--data-dir",
            str(data_dir),
            "--input",
            str(candidates),
        ],
    )

    fetch_stats.main()

    registry = json.loads((data_dir / "monitored_instances.json").read_text())
    assert registry == [
        {
            "host": "candidate.example",
            "url": "https://candidate.example",
            "source": "peer",
            "platform": "mastodon",
        }
    ]


def test_registry_aliases_collapse_to_one_canonical_host(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        instances=[],
        ok=[],
        monitored=[
            {"host": "old.example", "url": "https://old.example", "source": "peer"},
            {
                "host": "canonical.example",
                "url": "https://canonical.example",
                "source": "legacy",
            },
        ],
        aliases={"old.example": "canonical.example"},
    )
    fetch_stats.configure_data_dir(data_dir)

    registry = fetch_stats.load_monitored_registry()
    fetch_stats.save_monitored_registry_atomic(registry)

    saved = json.loads((data_dir / "monitored_instances.json").read_text())
    assert len(saved) == 1
    assert saved[0]["host"] == "canonical.example"
    assert saved[0]["source"] == "peer"


def test_workflow_persists_registry_through_staging_and_commit() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/update.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("data/monitored_instances.json") >= 3
    assert "tracked_outputs=(data/monitored_instances.json" in workflow
