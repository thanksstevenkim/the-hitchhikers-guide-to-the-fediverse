from __future__ import annotations

import json
from pathlib import Path

from scripts.build_software_review_queue import (
    build_classification_map,
    normalize_software_id,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_publishing_site_count_is_derived_from_taxonomy() -> None:
    stats = load_json(DATA_DIR / "stats.ok.json")
    taxonomy = load_json(DATA_DIR / "software_taxonomy.json")
    registry = load_json(DATA_DIR / "software_registry.json")
    assert isinstance(stats, list)
    assert isinstance(taxonomy, dict)
    assert isinstance(registry, dict)

    classification = build_classification_map(taxonomy)
    publishing_hosts = 0
    for row in stats:
        software = row.get("software") if isinstance(row, dict) else None
        raw_name = software.get("name") if isinstance(software, dict) else None
        software_id = normalize_software_id(raw_name)
        group_id = classification.get(software_id, "unknown")
        if taxonomy["groups"][group_id]["deployment_kind"] == (
            "activitypub_enabled_site"
        ):
            publishing_hosts += 1

    registry_publishing_hosts = sum(
        entry["healthy_instance_count"]
        for entry in registry["software"]
        if entry["deployment_kind"] == "activitypub_enabled_site"
    )

    assert publishing_hosts > 0
    assert publishing_hosts == registry_publishing_hosts


def test_reported_one_user_is_bounded_by_reporting_hosts() -> None:
    stats = load_json(DATA_DIR / "stats.ok.json")
    assert isinstance(stats, list)

    reporting_hosts = [
        row
        for row in stats
        if isinstance(row, dict)
        and isinstance(row.get("users_total"), (int, float))
        and not isinstance(row.get("users_total"), bool)
    ]
    one_user_hosts = [
        row for row in reporting_hosts if row.get("users_total") == 1
    ]

    assert 0 < len(one_user_hosts) <= len(reporting_hosts) <= len(stats)


def test_scope_summary_is_present_in_the_site() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "js" / "render.js").read_text(encoding="utf-8")

    for element_id in {
        "summary-verified-value",
        "summary-publishing-value",
        "summary-one-user-value",
        "summary-reporting-users-value",
        "dataset-summary-note",
    }:
        assert f'id="{element_id}"' in html

    assert '"activitypub_enabled_site"' in javascript
    assert "users_total) === 1" in javascript
