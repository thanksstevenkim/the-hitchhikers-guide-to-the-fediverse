#!/usr/bin/env python3
"""Validate tracked inputs and the statistics consumed by the website."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .build_software_registry import build_software_registry
except ImportError:  # pragma: no cover - direct script execution
    from build_software_registry import build_software_registry  # type: ignore[no-redef]


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
SOFTWARE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOFTWARE_GROUP_TYPES = {"family", "software", "category", "fallback"}
DEPLOYMENT_KINDS = {
    "federated_service",
    "activitypub_enabled_site",
    "federation_infrastructure",
    "unknown",
}


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


def validate_software_taxonomy(path: Path) -> dict[str, Any]:
    taxonomy = load_json(path)
    if not isinstance(taxonomy, dict):
        raise ValidationError(f"{path} must be a JSON object")
    if taxonomy.get("schema_version") != 1:
        raise ValidationError(f"{path}.schema_version must be 1")

    group_order = taxonomy.get("group_order")
    groups = taxonomy.get("groups")
    if not isinstance(group_order, list) or not group_order:
        raise ValidationError(f"{path}.group_order must be a non-empty array")
    if not isinstance(groups, dict) or not groups:
        raise ValidationError(f"{path}.groups must be a non-empty object")
    if not all(isinstance(group_id, str) for group_id in group_order):
        raise ValidationError(f"{path}.group_order must contain only strings")
    if len(group_order) != len(set(group_order)):
        raise ValidationError(f"{path}.group_order contains duplicate groups")
    if set(group_order) != set(groups):
        missing_from_order = sorted(set(groups) - set(group_order))
        missing_from_groups = sorted(set(group_order) - set(groups))
        raise ValidationError(
            f"{path} group_order and groups differ; "
            f"missing_from_order={missing_from_order}, "
            f"missing_from_groups={missing_from_groups}"
        )
    if group_order[-1] != "unknown":
        raise ValidationError(f"{path}.group_order must end with unknown")

    member_owners: dict[str, str] = {}
    fallback_groups: list[str] = []
    group_ids = set(groups)
    for group_id, group in groups.items():
        label = f"{path}.groups[{group_id!r}]"
        if not SOFTWARE_ID_RE.fullmatch(group_id):
            raise ValidationError(f"{label} has an invalid group ID")
        if not isinstance(group, dict):
            raise ValidationError(f"{label} must be an object")

        group_type = group.get("type")
        if group_type not in SOFTWARE_GROUP_TYPES:
            raise ValidationError(
                f"{label}.type must be one of: "
                + ", ".join(sorted(SOFTWARE_GROUP_TYPES))
            )
        if group_type == "fallback":
            fallback_groups.append(group_id)

        deployment_kind = group.get("deployment_kind")
        if deployment_kind not in DEPLOYMENT_KINDS:
            raise ValidationError(
                f"{label}.deployment_kind must be one of: "
                + ", ".join(sorted(DEPLOYMENT_KINDS))
            )
        if group_type == "fallback" and deployment_kind != "unknown":
            raise ValidationError(
                f"{label}.deployment_kind must be unknown for a fallback group"
            )
        if group_type != "fallback" and deployment_kind == "unknown":
            raise ValidationError(
                f"{label}.deployment_kind can only be unknown for a fallback group"
            )

        members = group.get("members")
        if not isinstance(members, list) or not all(
            isinstance(member, str) for member in members
        ):
            raise ValidationError(f"{label}.members must be a string array")
        if members != sorted(members):
            raise ValidationError(f"{label}.members must be sorted")
        if len(members) != len(set(members)):
            raise ValidationError(f"{label}.members contains duplicates")
        if group_type == "software" and members:
            raise ValidationError(f"{label} software groups cannot have members")

        for member in members:
            if not SOFTWARE_ID_RE.fullmatch(member):
                raise ValidationError(f"{label}.members contains invalid ID: {member}")
            if member in group_ids:
                raise ValidationError(
                    f"software ID {member} cannot be both a group and a member"
                )
            previous_owner = member_owners.get(member)
            if previous_owner is not None:
                raise ValidationError(
                    f"software ID {member} belongs to multiple groups: "
                    f"{previous_owner}, {group_id}"
                )
            member_owners[member] = group_id

    if fallback_groups != ["unknown"]:
        raise ValidationError(
            f"{path} must define unknown as its only fallback group"
        )

    return taxonomy


def validate_software_registry(
    path: Path,
    stats: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    registry = load_json(path)
    if not isinstance(registry, dict):
        raise ValidationError(f"{path} must be a JSON object")
    if registry.get("schema_version") != 1:
        raise ValidationError(f"{path}.schema_version must be 1")
    if registry.get("taxonomy_schema_version") != taxonomy.get("schema_version"):
        raise ValidationError(
            f"{path}.taxonomy_schema_version must match software taxonomy"
        )

    software = registry.get("software")
    if not isinstance(software, list):
        raise ValidationError(f"{path}.software must be an array")
    if registry.get("software_count") != len(software):
        raise ValidationError(f"{path}.software_count must match software length")

    seen_ids: set[str] = set()
    for index, entry in enumerate(software):
        label = f"{path}.software[{index}]"
        if not isinstance(entry, dict):
            raise ValidationError(f"{label} must be an object")
        software_id = require_nonempty_string(
            entry.get("software_id"), f"{label}.software_id"
        )
        if not SOFTWARE_ID_RE.fullmatch(software_id):
            raise ValidationError(f"{label}.software_id has an invalid ID")
        if software_id in seen_ids:
            raise ValidationError(f"duplicate registry software ID: {software_id}")
        seen_ids.add(software_id)

        group_id = require_nonempty_string(entry.get("group_id"), f"{label}.group_id")
        group = taxonomy["groups"].get(group_id)
        if not isinstance(group, dict):
            raise ValidationError(f"{label}.group_id is not in the taxonomy")
        if entry.get("group_type") != group.get("type"):
            raise ValidationError(f"{label}.group_type must match the taxonomy")
        if entry.get("deployment_kind") != group.get("deployment_kind"):
            raise ValidationError(
                f"{label}.deployment_kind must match the taxonomy"
            )
        if entry.get("classification_status") not in {
            "classified",
            "explicit_unknown",
            "unclassified",
        }:
            raise ValidationError(f"{label}.classification_status is invalid")
        count = entry.get("healthy_instance_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValidationError(
                f"{label}.healthy_instance_count must be a non-negative integer"
            )
        observed_names = entry.get("observed_names")
        if not isinstance(observed_names, list) or not all(
            isinstance(name, str) and name for name in observed_names
        ):
            raise ValidationError(f"{label}.observed_names must be a string array")
        if len(observed_names) != len(set(observed_names)):
            raise ValidationError(f"{label}.observed_names contains duplicates")
        if entry.get("last_observed_at") is not None:
            require_nonempty_string(
                entry["last_observed_at"], f"{label}.last_observed_at"
            )

    expected = build_software_registry(stats, taxonomy)
    if registry != expected:
        raise ValidationError(
            f"{path} is stale; regenerate it with build_software_registry.py"
        )
    return registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
    )
    return parser.parse_args()


def validate_data_dir(data_dir: Path) -> None:
    taxonomy = validate_software_taxonomy(data_dir / "software_taxonomy.json")
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
    stats = load_json(data_dir / "stats.ok.json")
    validate_software_registry(
        data_dir / "software_registry.json", stats, taxonomy
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
