from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from scripts import validate_data


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
    write_json(data_dir / "instances.json", [{"name": "A", "url": "https://a.example"}])
    write_json(data_dir / "stats.ok.json", ok)
    write_json(data_dir / "stats.bad.json", bad)
    write_json(data_dir / "manual_overrides.json", {})
    write_json(data_dir / "host_aliases.json", aliases or {})


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
