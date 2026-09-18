from __future__ import annotations

import json
from pathlib import Path

from scripts import build_software_registry


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


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
                "members": ["mystery"],
            },
        },
    }


def make_stat(
    host: str,
    software_name: str | None,
    fetched_at: str,
) -> dict[str, object]:
    return {
        "host": host,
        "software": {"name": software_name},
        "fetched_at": fetched_at,
    }


def test_registry_combines_taxonomy_and_healthy_observations() -> None:
    stats = [
        make_stat("one.example", "Mastodon", "2026-09-17T00:00:00Z"),
        make_stat("two.example", "mastodon", "2026-09-17T01:00:00Z"),
        make_stat("three.example", "New Thing", "2026-09-17T02:00:00Z"),
        make_stat("retired.example", "ap-tombstone", "2026-09-17T03:00:00Z"),
        make_stat("unnamed.example", None, "2026-09-17T04:00:00Z"),
    ]

    registry = build_software_registry.build_software_registry(stats, make_taxonomy())
    by_id = {entry["software_id"]: entry for entry in registry["software"]}

    assert registry["dataset_fetched_at"] == "2026-09-17T04:00:00Z"
    assert by_id["mastodon"] == {
        "software_id": "mastodon",
        "group_id": "mastodon",
        "group_type": "family",
        "deployment_kind": "federated_service",
        "classification_status": "classified",
        "healthy_instance_count": 2,
        "observed_names": ["Mastodon", "mastodon"],
        "last_observed_at": "2026-09-17T01:00:00Z",
    }
    assert by_id["hometown"]["healthy_instance_count"] == 0
    assert by_id["hollo"]["group_id"] == "social"
    assert by_id["mystery"]["classification_status"] == "explicit_unknown"
    assert by_id["new-thing"]["classification_status"] == "unclassified"
    assert by_id["new-thing"]["group_id"] == "unknown"
    assert "social" not in by_id
    assert "ap-tombstone" not in by_id
    assert "unknown" not in by_id


def test_tracked_registry_matches_current_inputs() -> None:
    stats = json.loads((DATA_DIR / "stats.ok.json").read_text(encoding="utf-8"))
    taxonomy = json.loads(
        (DATA_DIR / "software_taxonomy.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (DATA_DIR / "software_registry.json").read_text(encoding="utf-8")
    )

    assert registry == build_software_registry.build_software_registry(
        stats, taxonomy
    )


def test_workflow_generates_persists_and_publishes_registry() -> None:
    workflow = (ROOT / ".github/workflows/update.yml").read_text(encoding="utf-8")

    assert "python scripts/build_software_registry.py" in workflow
    assert "cp \"$staging_data/software_registry.json\" data/software_registry.json" in workflow
    assert "tracked_outputs=(" in workflow
    assert "data/software_registry.json" in workflow
    assert "data/software_registry.json _site/data/" in workflow
