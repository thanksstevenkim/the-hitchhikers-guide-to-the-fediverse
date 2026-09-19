from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from scripts import build_software_registry, validate_data


def make_record(host: str, *, good: bool) -> Dict[str, Any]:
    return {
        "host": host,
        "verified_activitypub": good,
        "software": {"name": "mastodon"} if good else {},
        "open_registrations": True if good else None,
        "users_total": 1 if good else None,
        "users_active_month": 1 if good else None,
        "statuses": 1 if good else None,
        "languages_detected": ["en"] if good else [],
        "fetched_at": "2026-08-24T00:00:00Z",
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def prepare_data(
    data_dir: Path,
    *,
    ok: List[Dict[str, Any]],
    bad: List[Dict[str, Any]],
    aliases: Optional[Dict[str, str]] = None,
) -> None:
    data_dir.mkdir()
    taxonomy = {
        "schema_version": 1,
        "group_order": ["mastodon", "unknown"],
        "groups": {
            "mastodon": {
                "type": "family",
                "deployment_kind": "federated_service",
                "members": [],
            },
            "unknown": {
                "type": "fallback",
                "deployment_kind": "unknown",
                "members": [],
            },
        },
    }
    write_json(data_dir / "software_taxonomy.json", taxonomy)
    write_json(data_dir / "instances.json", [{"name": "A", "url": "https://a.example"}])
    write_json(data_dir / "stats.ok.json", ok)
    write_json(
        data_dir / "software_registry.json",
        build_software_registry.build_software_registry(ok, taxonomy),
    )
    write_json(data_dir / "stats.bad.json", bad)
    write_json(data_dir / "manual_overrides.json", {})
    write_json(data_dir / "host_aliases.json", aliases or {})
    canonical_hosts = {
        (aliases or {}).get(record["host"], record["host"])
        for record in ok
    }
    write_json(
        data_dir / "monitored_instances.json",
        [
            {
                "host": host,
                "url": f"https://{host}",
                "source": "legacy",
            }
            for host in sorted(canonical_hosts)
        ]
        or [
            {
                "host": "a.example",
                "url": "https://a.example",
                "source": "seed",
            }
        ],
    )


@pytest.mark.parametrize("bucket", ["OK", "BAD"])
def test_duplicate_host_within_stats_file_is_rejected(
    tmp_path: Path, bucket: str
) -> None:
    path = tmp_path / "stats.json"
    good = bucket == "OK"
    write_json(path, [make_record("a.example", good=good)] * 2)

    with pytest.raises(validate_data.ValidationError, match="duplicate"):
        validate_data.validate_stats(
            path, {}, bucket=bucket, required=bucket == "OK"
        )


def test_same_host_in_ok_and_bad_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        ok=[make_record("a.example", good=True)],
        bad=[make_record("a.example", good=False)],
    )

    with pytest.raises(validate_data.ValidationError, match="both OK and BAD"):
        validate_data.validate_data_dir(data_dir)


def test_alias_equivalent_cross_bucket_host_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        ok=[make_record("a.example", good=True)],
        bad=[make_record("canonical.example", good=False)],
        aliases={"a.example": "canonical.example"},
    )

    with pytest.raises(validate_data.ValidationError, match="both OK and BAD"):
        validate_data.validate_data_dir(data_dir)


def test_duplicate_monitored_canonical_host_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        ok=[make_record("canonical.example", good=True)],
        bad=[],
        aliases={"old.example": "canonical.example"},
    )
    write_json(
        data_dir / "monitored_instances.json",
        [
            {
                "host": "old.example",
                "url": "https://old.example",
                "source": "legacy",
            },
            {
                "host": "canonical.example",
                "url": "https://canonical.example",
                "source": "peer",
            },
        ],
    )

    with pytest.raises(validate_data.ValidationError, match="canonical host"):
        validate_data.validate_data_dir(data_dir)


def test_ok_host_must_be_present_in_monitored_registry(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        ok=[make_record("displayed.example", good=True)],
        bad=[],
    )
    write_json(
        data_dir / "monitored_instances.json",
        [
            {
                "host": "other.example",
                "url": "https://other.example",
                "source": "seed",
            }
        ],
    )

    with pytest.raises(validate_data.ValidationError, match="missing from monitored"):
        validate_data.validate_data_dir(data_dir)


def test_stale_software_registry_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    prepare_data(
        data_dir,
        ok=[make_record("a.example", good=True)],
        bad=[],
    )
    registry_path = data_dir / "software_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["software"][0]["healthy_instance_count"] = 999
    write_json(registry_path, registry)

    with pytest.raises(validate_data.ValidationError, match="stale"):
        validate_data.validate_data_dir(data_dir)


def test_complete_language_provenance_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    record = make_record("a.example", good=True)
    record.update(
        {
            "languages_declared": ["ja"],
            "languages_inferred": ["zh"],
            "languages_document": [],
            "languages_overridden": [],
            "language_detection_version": 2,
            "language_detection_status": "current",
        }
    )
    write_json(path, [record])

    assert validate_data.validate_stats(
        path,
        {},
        bucket="OK",
        required=True,
    ) == {"a.example"}


def test_partial_language_provenance_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    record = make_record("a.example", good=True)
    record["languages_inferred"] = ["en"]
    write_json(path, [record])

    with pytest.raises(validate_data.ValidationError, match="partial language"):
        validate_data.validate_stats(path, {}, bucket="OK", required=True)
