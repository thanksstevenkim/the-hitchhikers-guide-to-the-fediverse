#!/usr/bin/env python3
"""Build a prioritized review queue for unclassified Fediverse software."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SOFTWARE_ID_PATTERN = re.compile(r"[^a-z0-9]+")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_software_id(value: Any) -> str:
    if value is None:
        return "unknown"
    normalized = SOFTWARE_ID_PATTERN.sub("-", str(value).strip().lower()).strip("-")
    return normalized or "unknown"


def build_classification_map(taxonomy: dict[str, Any]) -> dict[str, str]:
    classification: dict[str, str] = {}
    for group_id, group in taxonomy["groups"].items():
        classification[group_id] = group_id
        for member in group["members"]:
            classification[member] = group_id
    return classification


def build_review_queue(
    stats: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    sample_hosts: int = 3,
) -> dict[str, Any]:
    classification = build_classification_map(taxonomy)
    observations: dict[str, dict[str, Any]] = {}
    dataset_fetched_at: str | None = None

    for row in stats:
        if not isinstance(row, dict):
            continue
        software = row.get("software")
        raw_name = software.get("name") if isinstance(software, dict) else None
        software_id = normalize_software_id(raw_name)
        host = row.get("host")
        fetched_at = row.get("fetched_at")

        observation = observations.setdefault(
            software_id,
            {
                "raw_names": Counter(),
                "hosts": set(),
                "last_observed_at": None,
            },
        )
        if isinstance(raw_name, str) and raw_name.strip():
            observation["raw_names"][raw_name.strip()] += 1
        if isinstance(host, str) and host.strip():
            observation["hosts"].add(host.strip().lower())
        if isinstance(fetched_at, str) and fetched_at:
            previous = observation["last_observed_at"]
            if previous is None or fetched_at > previous:
                observation["last_observed_at"] = fetched_at
            if dataset_fetched_at is None or fetched_at > dataset_fetched_at:
                dataset_fetched_at = fetched_at

    queue: list[dict[str, Any]] = []
    for software_id, observation in observations.items():
        group_id = classification.get(software_id)
        if group_id and group_id != "unknown":
            continue

        raw_names = sorted(
            observation["raw_names"],
            key=lambda name: (-observation["raw_names"][name], name.lower()),
        )
        hosts = sorted(observation["hosts"])
        queue.append(
            {
                "software_id": software_id,
                "review_status": (
                    "explicit_unknown" if group_id == "unknown" else "unclassified"
                ),
                "current_group": group_id,
                "healthy_instance_count": len(hosts),
                "raw_names": raw_names,
                "raw_name_counts": {
                    name: observation["raw_names"][name] for name in raw_names
                },
                "sample_hosts": hosts[:sample_hosts],
                "last_observed_at": observation["last_observed_at"],
            }
        )

    queue.sort(
        key=lambda item: (
            -item["healthy_instance_count"],
            item["software_id"],
        )
    )
    return {
        "schema_version": 1,
        "dataset_fetched_at": dataset_fetched_at,
        "software_count": len(queue),
        "software": queue,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data",
        help="Directory containing stats.ok.json",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=None,
        help="Taxonomy path; defaults to software_taxonomy.json in --data-dir",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "data" / "software_review_queue.json"),
        help="Output path, or - for stdout",
    )
    parser.add_argument(
        "--sample-hosts",
        type=int,
        default=3,
        help="Maximum representative hosts per software entry",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sample_hosts < 0:
        print("--sample-hosts must be zero or greater", file=sys.stderr)
        return 2

    stats = load_json(args.data_dir.resolve() / "stats.ok.json")
    taxonomy_path = args.taxonomy or args.data_dir / "software_taxonomy.json"
    taxonomy = load_json(taxonomy_path.resolve())
    if not isinstance(stats, list):
        raise ValueError("stats.ok.json must be a JSON array")
    if not isinstance(taxonomy, dict):
        raise ValueError("software taxonomy must be a JSON object")

    queue = build_review_queue(stats, taxonomy, sample_hosts=args.sample_hosts)
    serialized = json.dumps(queue, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        sys.stdout.write(serialized)
    else:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
        print(
            f"software review queue written: {output_path} "
            f"({queue['software_count']} entries)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
