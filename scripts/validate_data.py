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


def load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_json(path)


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


def normalize_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if "://" in host:
        host = urlparse(host).hostname or ""
    elif ":" in host:
        name, port = host.rsplit(":", 1)
        if port.isdigit():
            host = name
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def resolve_canonical_host(host: str, aliases: dict[str, str]) -> str:
    current = normalize_host(host)
    seen: set[str] = set()
    while current:
        if current in seen:
            return min(seen)
        seen.add(current)
        target = normalize_host(aliases.get(current, ""))
        if not target or target == current:
            break
        current = target
    return current


def validate_stats(
    path: Path,
    aliases: dict[str, str],
    *,
    bucket: str,
    required: bool,
) -> set[str]:
    rows = load_json(path) if required else load_optional_json(path, [])
    if not isinstance(rows, list) or (required and not rows):
        requirement = "a non-empty JSON array" if required else "a JSON array"
        raise ValidationError(f"{path} must be {requirement}")

    seen_hosts: set[str] = set()
    seen_canonical_hosts: set[str] = set()
    for index, row in enumerate(rows):
        label = f"{path}[{index}]"
        if not isinstance(row, dict):
            raise ValidationError(f"{label} must be an object")
        missing = REQUIRED_STATS_FIELDS - row.keys()
        if missing:
            raise ValidationError(f"{label} is missing fields: {', '.join(sorted(missing))}")

        host = normalize_host(require_nonempty_string(row["host"], f"{label}.host"))
        if host in seen_hosts:
            raise ValidationError(f"duplicate {bucket} stats host: {host}")
        seen_hosts.add(host)
        canonical_host = resolve_canonical_host(host, aliases)
        if canonical_host in seen_canonical_hosts:
            raise ValidationError(
                f"duplicate {bucket} canonical host after aliases: {canonical_host}"
            )
        seen_canonical_hosts.add(canonical_host)

        verified = row["verified_activitypub"]
        if bucket == "OK" and verified is not True:
            raise ValidationError(f"{label}.verified_activitypub must be true")
        if bucket == "BAD" and not isinstance(verified, bool):
            raise ValidationError(f"{label}.verified_activitypub must be boolean")
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
        failures = row.get("consecutive_failures")
        if failures is not None and (
            not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 0
        ):
            raise ValidationError(f"{label}.consecutive_failures must be non-negative")
        if row.get("last_failure_at") is not None:
            require_nonempty_string(row["last_failure_at"], f"{label}.last_failure_at")
        if row.get("last_failure_reason") is not None:
            require_nonempty_string(
                row["last_failure_reason"], f"{label}.last_failure_reason"
            )

    return seen_canonical_hosts


def validate_monitored_registry(
    path: Path,
    aliases: dict[str, str],
) -> set[str]:
    rows = load_json(path)
    if not isinstance(rows, list) or not rows:
        raise ValidationError(f"{path} must be a non-empty JSON array")

    seen_hosts: set[str] = set()
    seen_canonical_hosts: set[str] = set()
    for index, row in enumerate(rows):
        label = f"{path}[{index}]"
        if not isinstance(row, dict):
            raise ValidationError(f"{label} must be an object")
        host = normalize_host(require_nonempty_string(row.get("host"), f"{label}.host"))
        if host in seen_hosts:
            raise ValidationError(f"duplicate monitored host: {host}")
        seen_hosts.add(host)

        canonical_host = resolve_canonical_host(host, aliases)
        if canonical_host in seen_canonical_hosts:
            raise ValidationError(
                "duplicate monitored canonical host after aliases: "
                f"{canonical_host}"
            )
        seen_canonical_hosts.add(canonical_host)

        url = require_nonempty_string(row.get("url"), f"{label}.url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValidationError(f"{label}.url must be an absolute HTTP(S) URL")
        url_host = resolve_canonical_host(parsed.hostname, aliases)
        if url_host != canonical_host:
            raise ValidationError(f"{label}.url host must match its canonical host")

        source = require_nonempty_string(row.get("source"), f"{label}.source")
        if source not in {"seed", "peer", "legacy"}:
            raise ValidationError(
                f"{label}.source must be one of: seed, peer, legacy"
            )

    return seen_canonical_hosts


def validate_mapping(path: Path, value_validator: type) -> dict[str, Any]:
    mapping = load_json(path)
    if not isinstance(mapping, dict):
        raise ValidationError(f"{path} must be a JSON object")
    for key, value in mapping.items():
        require_nonempty_string(key, f"{path} key")
        if not isinstance(value, value_validator):
            raise ValidationError(
                f"{path}[{key!r}] must be {value_validator.__name__}"
            )
    return mapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
    )
    return parser.parse_args()


def validate_data_dir(data_dir: Path) -> None:
    validate_instances(data_dir / "instances.json")
    validate_mapping(data_dir / "manual_overrides.json", dict)
    raw_aliases = validate_mapping(data_dir / "host_aliases.json", str)
    aliases = {
        normalize_host(key): normalize_host(value)
        for key, value in raw_aliases.items()
    }
    monitored_hosts = validate_monitored_registry(
        data_dir / "monitored_instances.json", aliases
    )
    ok_hosts = validate_stats(
        data_dir / "stats.ok.json", aliases, bucket="OK", required=True
    )
    bad_hosts = validate_stats(
        data_dir / "stats.bad.json", aliases, bucket="BAD", required=False
    )
    overlap = ok_hosts & bad_hosts
    if overlap:
        raise ValidationError(
            "hosts present in both OK and BAD stats after aliases: "
            + ", ".join(sorted(overlap))
        )
    unmonitored_ok = ok_hosts - monitored_hosts
    if unmonitored_ok:
        raise ValidationError(
            "OK stats hosts missing from monitored registry: "
            + ", ".join(sorted(unmonitored_ok))
        )


def main() -> int:
    data_dir = parse_args().data_dir.resolve()
    try:
        validate_data_dir(data_dir)
    except ValidationError as exc:
        print(f"data validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"data validation passed: {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
