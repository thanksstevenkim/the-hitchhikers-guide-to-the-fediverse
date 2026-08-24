from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from scripts import fetch_stats


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def prepare_data_dir(
    data_dir: Path,
    *,
    instances: List[object],
    ok: Optional[List[object]] = None,
    bad: Optional[List[object]] = None,
    aliases: Optional[Dict[str, str]] = None,
    monitored: Optional[List[object]] = None,
) -> None:
    data_dir.mkdir()
    write_json(data_dir / "instances.json", instances)
    write_json(data_dir / "stats.ok.json", ok or [])
    write_json(data_dir / "stats.bad.json", bad or [])
    write_json(data_dir / "host_aliases.json", aliases or {})
    write_json(data_dir / "manual_overrides.json", {})
    if monitored is not None:
        write_json(data_dir / "monitored_instances.json", monitored)


@pytest.mark.parametrize("stats_file", ["stats.ok.json", "stats.bad.json"])
def test_curated_instance_is_loaded_even_when_already_checked(
    tmp_path: Path, stats_file: str
) -> None:
    data_dir = tmp_path / "data"
    prepare_data_dir(
        data_dir,
        instances=[{"name": "Seed A", "url": "https://a.example"}],
    )
    write_json(data_dir / stats_file, [{"host": "a.example"}])
    fetch_stats.configure_data_dir(data_dir)

    instances = list(fetch_stats.load_instances(fetch_stats.INSTANCES_PATH))

    assert [instance.host for instance in instances] == ["a.example"]


def test_curated_instance_alias_is_applied_without_skipping_refresh(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    prepare_data_dir(
        data_dir,
        instances=[{"name": "Seed A", "url": "https://a.example"}],
        ok=[{"host": "canonical.example"}],
        aliases={"a.example": "canonical.example"},
    )
    fetch_stats.configure_data_dir(data_dir)

    instances = list(fetch_stats.load_instances(fetch_stats.INSTANCES_PATH))

    assert [instance.host for instance in instances] == ["canonical.example"]


def test_candidate_input_still_skips_already_checked_hosts(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data_dir(
        data_dir,
        instances=[],
        ok=[{"host": "a.example"}],
    )
    candidates = data_dir / "peer_suggestions.json"
    write_json(candidates, ["a.example", "b.example"])
    fetch_stats.configure_data_dir(data_dir)

    instances = list(fetch_stats.load_host_strings(candidates))

    assert [instance.host for instance in instances] == ["b.example"]


def test_candidate_input_skips_monitored_host_without_stats(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data_dir(
        data_dir,
        instances=[],
        monitored=[
            {
                "host": "known.example",
                "url": "https://known.example",
                "source": "peer",
            }
        ],
    )
    candidates = data_dir / "peer_suggestions.json"
    write_json(candidates, ["known.example", "new.example"])
    fetch_stats.configure_data_dir(data_dir)

    instances = list(fetch_stats.load_host_strings(candidates))

    assert [instance.host for instance in instances] == ["new.example"]


def test_discover_peers_processes_an_already_checked_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    prepare_data_dir(
        data_dir,
        instances=[{"name": "Seed A", "url": "https://a.example"}],
        ok=[{"host": "a.example"}],
    )
    processed: list[str] = []

    def fake_process(
        instance: fetch_stats.Instance,
        timestamp: str,
        *,
        discover_peers: bool = False,
    ):
        processed.append(instance.host)
        return (
            {
                "host": instance.host,
                "verified_activitypub": True,
                "software": {"name": "mastodon", "version": "test"},
                "open_registrations": True,
                "users_total": 1,
                "users_active_month": 1,
                "statuses": 1,
                "languages_detected": ["en"],
                "fetched_at": timestamp,
            },
            [],
            {"new-peer.example"},
        )

    monkeypatch.setattr(fetch_stats, "process_instance", fake_process)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fetch_stats.py",
            "--data-dir",
            str(data_dir),
            "--discover-peers",
        ],
    )

    fetch_stats.main()

    assert processed == ["a.example"]
    assert json.loads((data_dir / "peer_suggestions.json").read_text()) == [
        "new-peer.example"
    ]


def test_empty_curated_list_is_the_no_instances_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    data_dir = tmp_path / "data"
    prepare_data_dir(data_dir, instances=[])
    monkeypatch.setattr(
        "sys.argv", ["fetch_stats.py", "--data-dir", str(data_dir)]
    )

    with caplog.at_level(logging.ERROR):
        fetch_stats.main()

    assert "No instances to process" in caplog.text
