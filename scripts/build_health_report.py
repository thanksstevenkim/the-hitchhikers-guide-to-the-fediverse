#!/usr/bin/env python3
"""Summarize daily collection health without changing collector classifications.

The snapshot is an operational history, not a public source of instance stats.
Its failed_observations streak starts when this report first becomes available.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

try:
    from .validate_data import normalize_host, resolve_canonical_host
except ImportError:  # Running as a script from the repository root.
    from validate_data import normalize_host, resolve_canonical_host


SCHEMA_VERSION = 1
STATES = {"GOOD", "WARN", "BAD", "MISSING"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: str, aliases: dict[str, str]) -> str:
    return resolve_canonical_host(normalize_host(value), aliases)


def host_from_row(row: Any, aliases: dict[str, str]) -> str:
    if isinstance(row, str):
        raw = row
    elif isinstance(row, dict):
        raw = str(row.get("host") or urlparse(str(row.get("url", ""))).hostname or "")
    else:
        raw = ""
    host = canonical(raw, aliases)
    if not host:
        raise ValueError(f"invalid monitored/seed host: {row!r}")
    return host


def reason_code(record: dict[str, Any]) -> str:
    reason = str(record.get("last_failure_reason") or "")
    if not reason:
        errors = record.get("errors")
        if isinstance(errors, list):
            reason = "; ".join(str(e) for e in errors)
    s = reason.lower()
    if "terminal software marker" in s:
        return "TERMINAL"
    if any(x in s for x in ("nameresolutionerror", "failed to resolve", "name or service not known", "temporary failure in name resolution", "no address associated with hostname")):
        return "DNS"
    if any(x in s for x in ("sslerror", "certificate_verify_failed", "tlsv1_", "ssl:")):
        return "TLS"
    if any(x in s for x in ("timed out", "timeout", "time out")):
        return "TIMEOUT"
    status = re.search(r"\bhttp (\d{3})\b", s)
    if status:
        code = int(status.group(1))
        if code == 429:
            return "HTTP_429"
        if 500 <= code <= 599:
            return "HTTP_5XX"
        if 400 <= code <= 499:
            return "HTTP_4XX"
        return "HTTP_OTHER"
    if "redirect" in s:
        return "REDIRECT"
    if any(x in s for x in ("content-type", "invalid json", "jsondecodeerror", "parse")):
        return "INVALID_RESPONSE"
    if any(x in s for x in ("anomalous", "invalid metrics")):
        return "ANOMALOUS"
    return "OTHER"


def load_previous(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported previous health snapshot schema")
    hosts = data.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("previous health snapshot must contain a hosts object")
    for host, entry in hosts.items():
        if not isinstance(entry, dict) or entry.get("status") not in STATES:
            raise ValueError(f"invalid previous snapshot host state: {host}")
    return data


def make_health_report(
    data_dir: Path, previous: dict[str, Any] | None, now: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    aliases = load_json(data_dir / "host_aliases.json")
    if not isinstance(aliases, dict):
        raise ValueError("host_aliases.json must be an object")
    monitored = {
        host_from_row(row, aliases)
        for row in load_json(data_dir / "monitored_instances.json")
    }
    seeds = {
        host_from_row(row, aliases)
        for row in load_json(data_dir / "instances.json")
    }
    if not monitored or not seeds:
        raise ValueError("empty monitored or seed registry")
    if not seeds.issubset(monitored):
        raise ValueError("one or more seed hosts are not monitored")

    observed: dict[str, tuple[str, str | None]] = {}
    for filename, bad in (("stats.ok.json", False), ("stats.bad.json", True)):
        rows = load_json(data_dir / filename)
        if not isinstance(rows, list):
            raise ValueError(f"{filename} must be an array")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"invalid row in {filename}")
            host = canonical(str(row.get("host", "")), aliases)
            if not host or host not in monitored or host in observed:
                raise ValueError(f"unexpected/duplicate stats host in {filename}: {host}")
            status = "BAD" if bad else ("WARN" if row.get("last_failure_at") else "GOOD")
            code = reason_code(row) if status != "GOOD" else None
            observed[host] = (status, code)

    prior_hosts = previous["hosts"] if previous else {}
    snapshot_hosts: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    new_hosts = monitored - prior_hosts.keys() if previous else set()
    removed_hosts = prior_hosts.keys() - monitored if previous else set()

    for host in sorted(monitored):
        status, reason = observed.get(host, ("MISSING", "NO_OBSERVATION"))
        counts[status] += 1
        prev = prior_hosts.get(host)
        if prev and prev["status"] != status:
            transitions[f'{prev["status"]}->{status}'] += 1
        since = prev["since_at"] if prev and prev["status"] == status else now
        entry: dict[str, Any] = {"status": status, "since_at": since}
        if status != "GOOD":
            entry["reason"] = reason
            reasons[reason or "OTHER"] += 1
            was_failing = prev and prev["status"] in {"WARN", "BAD", "MISSING"}
            entry["failed_observations"] = (
                int(prev.get("failed_observations", 0)) + 1 if was_failing else 1
            )
        snapshot_hosts[host] = entry

    current = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "hosts": snapshot_hosts,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "baseline": previous is None,
        "previous_generated_at": previous.get("generated_at") if previous else None,
        "total_monitored": len(monitored),
        "counts": {state: counts[state] for state in ("GOOD", "WARN", "BAD", "MISSING")},
        "total_seeds": len(seeds),
        "seed_states": {
            state: sum(snapshot_hosts[host]["status"] == state for host in seeds)
            for state in ("GOOD", "WARN", "BAD", "MISSING")
        },
        "failure_reason_counts": dict(sorted(reasons.items())),
        "transitions": dict(sorted(transitions.items())) if previous else {},
        "new_hosts": len(new_hosts) if previous else None,
        "removed_hosts": len(removed_hosts) if previous else None,
        "failed_three_or_more_observations": sum(
            e.get("failed_observations", 0) >= 3 for e in snapshot_hosts.values()
        ),
        "new_bad_examples": (
            sorted(
                host for host, e in snapshot_hosts.items()
                if e["status"] == "BAD"
                and prior_hosts.get(host, {}).get("status") != "BAD"
                and host in prior_hosts
            )[:20]
            if previous else []
        ),
    }
    if sum(counts.values()) != len(monitored):
        raise ValueError("health counts do not cover monitored registry")
    return current, report


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "## Host collection health",
        "",
        f'- Report time (UTC): {report["generated_at"]}',
        f'- Monitored hosts: **{report["total_monitored"]}**',
        f'- GOOD / WARN / BAD / MISSING: **{counts["GOOD"]} / {counts["WARN"]} / {counts["BAD"]} / {counts["MISSING"]}**',
        f'- Seed GOOD / WARN / BAD / MISSING: **{report["seed_states"]["GOOD"]} / {report["seed_states"]["WARN"]} / {report["seed_states"]["BAD"]} / {report["seed_states"]["MISSING"]}**',
        f'- Failed on at least 3 consecutive observed runs: **{report["failed_three_or_more_observations"]}**',
        "",
    ]
    if report["baseline"]:
        lines.extend([
            "**Initial baseline:** no prior snapshot; transitions and pre-baseline streaks are unknown.",
            "",
        ])
    else:
        lines.extend([
            f'- Previous report: {report["previous_generated_at"]}',
            f'- New / removed monitored hosts: **{report["new_hosts"]} / {report["removed_hosts"]}**',
            "",
            "### Status transitions",
            "",
        ])
        if report["transitions"]:
            lines.extend(
                f'- {change}: **{count}**'
                for change, count in report["transitions"].items()
            )
        else:
            lines.append("- No changes among hosts present in both snapshots")
        lines.append("")
    lines.extend(["### Failure categories (best-effort)", ""])
    if report["failure_reason_counts"]:
        lines.extend(
            f'- {reason}: **{count}**'
            for reason, count in sorted(
                report["failure_reason_counts"].items(), key=lambda x: (-x[1], x[0])
            )
        )
    else:
        lines.append("- None")
    lines.extend([
        "",
        "The report describes collection observations, not confirmed server outages.",
        "BAD details are still local to the collector. This snapshot does not change classification, retries, or published site data.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--previous-snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        previous = load_previous(args.previous_snapshot)
        current, report = make_health_report(
            args.data_dir, previous, datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        outputs = (
            (args.snapshot_out, json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"),
            (args.report_out, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
            (args.summary_out, render_markdown(report)),
        )
        for path, body in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        print(render_markdown(report))
        return 0
    except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        parser.exit(1, f"health report failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
