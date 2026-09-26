from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_software_review_queue, validate_data


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "data" / "software_taxonomy.json"
STATS_PATH = ROOT / "data" / "stats.ok.json"


def make_taxonomy() -> dict[str, object]:
    return {
        "schema_version": 1,
        "group_order": ["mastodon", "social", "unknown"],
        "groups": {
            "mastodon": {
                "type": "family",
                "deployment_kind": "federated_service",
                "members": ["hometown"],
            },
            "social": {
                "type": "category",
                "deployment_kind": "federated_service",
                "members": ["hollo"],
            },
            "unknown": {
                "type": "fallback",
                "deployment_kind": "unknown",
                "members": ["mystery-software"],
            },
        },
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def make_stat(host: str, software_name: str, fetched_at: str) -> dict[str, object]:
    return {
        "host": host,
        "software": {"name": software_name},
        "fetched_at": fetched_at,
    }


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("IceShrimp.NET", "iceshrimp-net"),
        ("Nextcloud Social", "nextcloud-social"),
        ("  New Thing  ", "new-thing"),
        (None, "unknown"),
    ],
)
def test_software_name_normalization_matches_ui_ids(
    raw_name: object, expected: str
) -> None:
    assert build_software_review_queue.normalize_software_id(raw_name) == expected


def test_tracked_software_taxonomy_is_valid() -> None:
    validate_data.validate_software_taxonomy(TAXONOMY_PATH)


def test_reviewed_software_has_expected_groups() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    classification = build_software_review_queue.build_classification_map(taxonomy)

    assert classification["starling"] == "social"
    assert classification["welley"] == "social"
    assert classification["cyclone"] == "social"
    assert classification["plattform-activitypub"] == "social"
    assert classification["posterchan"] == "social"
    assert classification["blackbirb"] == "blog"
    assert classification["klonkt"] == "blog"
    assert classification["concrnt-ap-bridge"] == "bridge"
    assert "ap-tombstone" not in classification


def test_repository_declared_forks_use_their_parent_family() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    classification = build_software_review_queue.build_classification_map(taxonomy)

    for software_id in {
        "areionskey",
        "cluckey",
        "corpsekey",
        "mk-go",
        "pulsar",
        "shorkey",
        "turtkey",
    }:
        assert classification[software_id] == "misskey"


def test_reviewed_specialized_software_uses_functional_categories() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    classification = build_software_review_queue.build_classification_map(taxonomy)

    assert classification["funkwhale"] == "audio"
    assert classification["mobilizon"] == "events"
    assert classification["forgejo"] == "forge"
    assert classification["postmarks"] == "bookmarks"
    assert classification["badgefed"] == "credentials"
    assert classification["activitypub-server"] == "infrastructure"


def test_deployment_kinds_separate_enabled_sites_and_infrastructure() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    groups = taxonomy["groups"]

    assert groups["mastodon"]["deployment_kind"] == "federated_service"
    assert groups["wordpress"]["deployment_kind"] == (
        "activitypub_enabled_site"
    )
    assert groups["ghost"]["deployment_kind"] == "activitypub_enabled_site"
    assert groups["relay"]["deployment_kind"] == "federation_infrastructure"
    assert groups["unknown"]["deployment_kind"] == "unknown"


def test_current_healthy_snapshot_is_fully_reviewed() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))

    queue = build_software_review_queue.build_review_queue(stats, taxonomy)
    queued_ids = {
        item["software_id"]
        for item in queue["software"]
        if item["review_status"] == "unclassified"
    }

    assert queued_ids <= {"ap-tombstone"}


def test_duplicate_software_membership_is_rejected(tmp_path: Path) -> None:
    taxonomy = make_taxonomy()
    taxonomy["groups"]["social"]["members"].append("hometown")  # type: ignore[index]
    path = tmp_path / "software_taxonomy.json"
    write_json(path, taxonomy)

    with pytest.raises(validate_data.ValidationError, match="multiple groups"):
        validate_data.validate_software_taxonomy(path)


def test_group_order_must_cover_every_group(tmp_path: Path) -> None:
    taxonomy = make_taxonomy()
    taxonomy["group_order"].remove("social")  # type: ignore[union-attr]
    path = tmp_path / "software_taxonomy.json"
    write_json(path, taxonomy)

    with pytest.raises(validate_data.ValidationError, match="group_order and groups differ"):
        validate_data.validate_software_taxonomy(path)


def test_invalid_deployment_kind_is_rejected(tmp_path: Path) -> None:
    taxonomy = make_taxonomy()
    taxonomy["groups"]["social"]["deployment_kind"] = "proper_instance"  # type: ignore[index]
    path = tmp_path / "software_taxonomy.json"
    write_json(path, taxonomy)

    with pytest.raises(validate_data.ValidationError, match="deployment_kind"):
        validate_data.validate_software_taxonomy(path)


def test_review_queue_prioritizes_unknown_and_unclassified_software() -> None:
    stats = [
        make_stat("mastodon.example", "mastodon", "2026-09-17T00:00:00Z"),
        make_stat("hometown.example", "Hometown", "2026-09-17T01:00:00Z"),
        make_stat("mystery-a.example", "Mystery Software", "2026-09-17T02:00:00Z"),
        make_stat("mystery-b.example", "mystery-software", "2026-09-17T03:00:00Z"),
        make_stat("new.example", "New Thing", "2026-09-17T04:00:00Z"),
    ]

    result = build_software_review_queue.build_review_queue(
        stats,
        make_taxonomy(),
        sample_hosts=1,
    )

    assert result["dataset_fetched_at"] == "2026-09-17T04:00:00Z"
    assert result["software_count"] == 2
    assert [item["software_id"] for item in result["software"]] == [
        "mystery-software",
        "new-thing",
    ]
    assert result["software"][0]["review_status"] == "explicit_unknown"
    assert result["software"][0]["healthy_instance_count"] == 2
    assert result["software"][0]["raw_name_counts"] == {
        "Mystery Software": 1,
        "mystery-software": 1,
    }
    assert result["software"][0]["sample_hosts"] == ["mystery-a.example"]
    assert result["software"][1]["review_status"] == "unclassified"
