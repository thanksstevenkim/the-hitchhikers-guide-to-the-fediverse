#!/usr/bin/env python3
"""Validate tracked inputs and the statistics consumed by the website."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REQUIRED_STATS_FIELDS = {
    "host",
    "verified_activitypub",
    "software",
    "open_registrations",
    "users_total",
    "users_active_month",
    "statuses",
    "languages_detected",
    "fetched_at",
}
NUMERIC_FIELDS = ("users_total", "users_active_month", "statuses")


class ValidationError(ValueError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in {path}: {exc}") from exc


def require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")
    return value.strip()


def validate_instances(path: Path) -> None:
    rows = load_json(path)
    if not isinstance(rows, list) or not rows:
        raise ValidationError(f"{path} must be a non-empty JSON array")

    seen_urls: set[str] = set()
    for index, row in enumerate(rows):
        label = f"{path}[{index}]"
        if not isinstance(row, dict):
            raise ValidationError(f"{label} must be an object")
        require_nonempty_string(row.get("name"), f"{label}.name")
        url = require_nonempty_string(row.get("url"), f"{label}.url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValidationError(f"{label}.url must be an absolute HTTP(S) URL")
        normalized = url.rstrip("/").lower()
        if normalized in seen_urls:
            raise ValidationError(f"duplicate instance URL: {url}")
        seen_urls.add(normalized)


def validate_stats(path: Path) -> None:
    rows = load_json(path)
    if not isinstance(rows, list) or not rows:
        raise ValidationError(f"{path} must be a non-empty JSON array")

    seen_hosts: set[str] = set()
    for index, row in enumerate(rows):
        label = f"{path}[{index}]"
        if not isinstance(row, dict):
            raise ValidationError(f"{label} must be an object")
        missing = REQUIRED_STATS_FIELDS - row.keys()
        if missing:
            raise ValidationError(f"{label} is missing fields: {', '.join(sorted(missing))}")

        host = require_nonempty_string(row["host"], f"{label}.host").lower()
        if host in seen_hosts:
            raise ValidationError(f"duplicate stats host: {host}")
        seen_hosts.add(host)

        if row["verified_activitypub"] is not True:
            raise ValidationError(f"{label}.verified_activitypub must be true")
        if not isinstance(row["software"], dict):
            raise ValidationError(f"{label}.software must be an object")
        if row["open_registrations"] is not None and not isinstance(
            row["open_registrations"], bool
        ):
            raise ValidationError(f"{label}.open_registrations must be boolean or null")
        for field in NUMERIC_FIELDS:
            value = row[field]
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValidationError(f"{label}.{field} must be non-negative or null")
        languages = row["languages_detected"]
        if not isinstance(languages, list) or not all(
            isinstance(language, str) and language for language in languages
        ):
            raise ValidationError(f"{label}.languages_detected must be a string array")
        require_nonempty_string(row["fetched_at"], f"{label}.fetched_at")


def validate_mapping(path: Path, value_validator: type) -> None:
    mapping = load_json(path)
    if not isinstance(mapping, dict):
        raise ValidationError(f"{path} must be a JSON object")
    for key, value in mapping.items():
        require_nonempty_string(key, f"{path} key")
        if not isinstance(value, value_validator):
            raise ValidationError(
                f"{path}[{key!r}] must be {value_validator.__name__}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
    )
    return parser.parse_args()


def main() -> int:
    data_dir = parse_args().data_dir.resolve()
    try:
        validate_instances(data_dir / "instances.json")
        validate_stats(data_dir / "stats.ok.json")
        validate_mapping(data_dir / "manual_overrides.json", dict)
        validate_mapping(data_dir / "host_aliases.json", str)
    except ValidationError as exc:
        print(f"data validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"data validation passed: {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
