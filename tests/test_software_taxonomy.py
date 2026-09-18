from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_software_review_queue, validate_data


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "data" / "software_taxonomy.json"


def make_taxonomy() -> dict[str, object]:
    return {
        "schema_version": 1,
        "group_order": ["mastodon", "social", "unknown"],
        "groups": {
            "mastodon": {"type": "family", "members": ["hometown"]},
            "social": {"type": "category", "members": ["hollo"]},
            "unknown": {
                "type": "fallback",
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
