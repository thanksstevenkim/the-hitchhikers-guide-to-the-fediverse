#!/usr/bin/env python3
"""Build a public software registry from healthy stats and the taxonomy."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from .build_software_review_queue import (
        build_classification_map,
        normalize_software_id,
    )
except ImportError:  # pragma: no cover - direct script execution
    from build_software_review_queue import (  # type: ignore[no-redef]
        build_classification_map,
        normalize_software_id,
    )


ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_SOFTWARE_IDS = frozenset({"ap-tombstone"})


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_software_ids(taxonomy: dict[str, Any]) -> set[str]:
    software_ids: set[str] = set()
    for group_id, group in taxonomy["groups"].items():
        if group["type"] in {"family", "software"}:
            software_ids.add(group_id)
        software_ids.update(group["members"])
    return software_ids


def build_software_registry(
    stats: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    classification = build_classification_map(taxonomy)
    observations: dict[str, dict[str, Any]] = {}
    dataset_fetched_at: str | None = None

    for row in stats:
        if not isinstance(row, dict):
            continue
        fetched_at = row.get("fetched_at")
        if isinstance(fetched_at, str) and fetched_at:
            if dataset_fetched_at is None or fetched_at > dataset_fetched_at:
                dataset_fetched_at = fetched_at

        software = row.get("software")
        raw_name = software.get("name") if isinstance(software, dict) else None
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        software_id = normalize_software_id(raw_name)
        if software_id in EXCLUDED_SOFTWARE_IDS:
            continue

        observation = observations.setdefault(
            software_id,
            {
                "raw_names": Counter(),
                "hosts": set(),
                "last_observed_at": None,
            },
        )
        observation["raw_names"][raw_name.strip()] += 1
        host = row.get("host")
        if isinstance(host, str) and host.strip():
            observation["hosts"].add(host.strip().lower())
        if isinstance(fetched_at, str) and fetched_at:
            previous = observation["last_observed_at"]
            if previous is None or fetched_at > previous:
                observation["last_observed_at"] = fetched_at

    software_ids = tracked_software_ids(taxonomy) | set(observations)
    group_order = {
        group_id: index for index, group_id in enumerate(taxonomy["group_order"])
    }
    entries: list[dict[str, Any]] = []

    for software_id in software_ids:
        mapped_group = classification.get(software_id)
        if mapped_group is None:
            group_id = "unknown"
            classification_status = "unclassified"
        elif mapped_group == "unknown":
            group_id = "unknown"
            classification_status = "explicit_unknown"
        else:
            group_id = mapped_group
            classification_status = "classified"

        observation = observations.get(software_id)
        raw_names = (
            sorted(
                observation["raw_names"],
                key=lambda name: (
                    -observation["raw_names"][name],
                    name.casefold(),
                    name,
                ),
            )
            if observation
            else []
        )
        entries.append(
            {
                "software_id": software_id,
                "group_id": group_id,
                "group_type": taxonomy["groups"][group_id]["type"],
                "classification_status": classification_status,
                "healthy_instance_count": (
                    len(observation["hosts"]) if observation else 0
                ),
                "observed_names": raw_names,
                "last_observed_at": (
                    observation["last_observed_at"] if observation else None
                ),
            }
        )

    entries.sort(
        key=lambda entry: (
            group_order[entry["group_id"]],
            entry["software_id"],
        )
    )
    return {
        "schema_version": 1,
        "taxonomy_schema_version": taxonomy["schema_version"],
        "dataset_fetched_at": dataset_fetched_at,
        "software_count": len(entries),
        "software": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data",
        help="Directory containing stats.ok.json and software_taxonomy.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path; defaults to software_registry.json in --data-dir, or -",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    stats = load_json(data_dir / "stats.ok.json")
    taxonomy = load_json(data_dir / "software_taxonomy.json")
    if not isinstance(stats, list):
        raise ValueError("stats.ok.json must be a JSON array")
    if not isinstance(taxonomy, dict):
        raise ValueError("software_taxonomy.json must be a JSON object")

    registry = build_software_registry(stats, taxonomy)
    serialized = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    output = args.output or str(data_dir / "software_registry.json")
    if output == "-":
        sys.stdout.write(serialized)
    else:
        output_path = Path(output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
        print(
            f"software registry written: {output_path} "
            f"({registry['software_count']} entries)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
