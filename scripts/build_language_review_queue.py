#!/usr/bin/env python3
"""Build a focused queue for language classifications that need human review."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from . import fetch_stats
except ImportError:  # pragma: no cover - direct script execution
    import fetch_stats  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATS_PATH = ROOT / "data" / "stats.ok.json"
DEFAULT_OVERRIDES_PATH = ROOT / "data" / "manual_overrides.json"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "language_review_queue.json"


def _is_han_only_cjk(text: str) -> bool:
    return (
        any(fetch_stats._is_han(ch) for ch in text)
        and not any(fetch_stats._is_kana(ch) for ch in text)
        and not any(fetch_stats._is_hangul(ch) for ch in text)
    )


def review_reasons(
    record: Dict[str, Any],
    has_override: bool = False,
    *,
    include_legacy: bool = False,
) -> List[str]:
    if has_override or record.get("language_detection_status") == "manual_override":
        return []

    reasons: List[str] = []
    status = record.get("language_detection_status")
    declared = set(fetch_stats.normalized_language_list(record.get("languages_declared")))
    inferred = set(fetch_stats.normalized_language_list(record.get("languages_inferred")))
    detected = set(fetch_stats.normalized_language_list(record.get("languages_detected")))
    description = str(record.get("nodeinfo_description") or "")

    if include_legacy and (status == "legacy_fallback" or not status):
        reasons.append("legacy_fallback")

    if declared and inferred and declared.isdisjoint(inferred):
        reasons.append("declared_inferred_conflict")

    if _is_han_only_cjk(description):
        if fetch_stats._has_strong_chinese_signal(description) and "zh" not in detected:
            reasons.append("strong_chinese_signal_missing")
        elif not inferred and "zh" not in declared:
            reasons.append("ambiguous_han_only")

    return reasons


def build_review_queue(
    stats: List[Dict[str, Any]],
    overrides: Dict[str, Dict[str, Any]],
    *,
    include_legacy: bool = False,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()

    for record in stats:
        host = str(record.get("host") or "").strip().lower()
        if not host:
            continue
        reasons = review_reasons(
            record,
            host in overrides,
            include_legacy=include_legacy,
        )
        if not reasons:
            continue
        reason_counts.update(reasons)
        software = record.get("software")
        software_name = (
            str(software.get("name") or "").strip()
            if isinstance(software, dict)
            else ""
        )
        rows.append(
            {
                "host": host,
                "reasons": reasons,
                "languages_detected": fetch_stats.normalized_language_list(
                    record.get("languages_detected")
                ),
                "languages_declared": fetch_stats.normalized_language_list(
                    record.get("languages_declared")
                ),
                "languages_inferred": fetch_stats.normalized_language_list(
                    record.get("languages_inferred")
                ),
                "language_detection_status": record.get(
                    "language_detection_status"
                ),
                "software": software_name or None,
                "description": record.get("nodeinfo_description"),
            }
        )

    rows.sort(key=lambda row: (row["reasons"], row["host"]))
    fetched_values = [
        str(record.get("fetched_at"))
        for record in stats
        if record.get("fetched_at")
    ]
    return {
        "schema_version": 1,
        "dataset_fetched_at": max(fetched_values, default=None),
        "instance_count": len(rows),
        "reason_counts": dict(sorted(reason_counts.items())),
        "instances": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS_PATH)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Also queue every record that had to preserve an unverified legacy label.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
    if not isinstance(stats, list):
        raise ValueError(f"{args.stats} must contain a JSON array")
    if not isinstance(overrides, dict):
        raise ValueError(f"{args.overrides} must contain a JSON object")

    queue = build_review_queue(
        stats,
        overrides,
        include_legacy=args.include_legacy,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {queue['instance_count']} language review candidates "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
