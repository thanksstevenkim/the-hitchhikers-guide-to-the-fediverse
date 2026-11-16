"""Operational health report tests; no network calls or production data changes."""
import json

import pytest

from scripts.build_health_report import (
    load_previous,
    make_health_report,
    reason_code,
    render_markdown,
)


def write_data(root, *, ok, bad, monitored=None):
    root.mkdir(exist_ok=True)
    monitored = monitored or ["seed.example", "warn.example", "bad.example", "missing.example"]
    docs = {
        "host_aliases.json": {},
        "monitored_instances.json": [{"host": host, "url": f"https://{host}"} for host in monitored],
        "instances.json": [{"name": "seed", "url": "https://seed.example"}],
        "stats.ok.json": ok,
        "stats.bad.json": bad,
    }
    for filename, contents in docs.items():
        (root / filename).write_text(json.dumps(contents), encoding="utf-8")


def good(host, *, warning=False):
    row = {"host": host, "fetched_at": "2026-11-16T00:00:00Z"}
    if warning:
        row.update(
            last_failure_at="2026-11-16T00:00:00Z",
            last_failure_reason="nodeinfo: Read timed out.",
        )
    return row


def bad(host, reason="nodeinfo: HTTP 503 from https://bad.example/nodeinfo"):
    return {"host": host, "last_failure_reason": reason}


def test_first_run_is_baseline_not_fabricated_transition(tmp_path):
    write_data(tmp_path, ok=[good("seed.example"), good("warn.example", warning=True)],
               bad=[bad("bad.example")])
    snapshot, report = make_health_report(tmp_path, None, "2026-11-16T00:00:00+00:00")

    assert report["baseline"] is True
    assert report["transitions"] == {}
    assert report["new_hosts"] is None
    assert report["counts"] == {"GOOD": 1, "WARN": 1, "BAD": 1, "MISSING": 1}
    assert report["seed_states"]["GOOD"] == 1
    assert report["failure_reason_counts"] == {
        "HTTP_5XX": 1, "NO_OBSERVATION": 1, "TIMEOUT": 1
    }
    assert "no prior snapshot" in render_markdown(report)
    assert snapshot["hosts"]["bad.example"]["failed_observations"] == 1


def test_status_transitions_and_streaks_across_days(tmp_path):
    write_data(tmp_path, ok=[good("seed.example"), good("warn.example", warning=True)],
               bad=[bad("bad.example")])
    first, _ = make_health_report(tmp_path, None, "2026-11-16T00:00:00+00:00")
    write_data(tmp_path, ok=[good("warn.example"), good("bad.example"), good("missing.example")],
               bad=[bad("seed.example")])
    second, report = make_health_report(tmp_path, first, "2026-11-17T00:00:00+00:00")

    assert report["transitions"] == {
        "BAD->GOOD": 1, "GOOD->BAD": 1, "MISSING->GOOD": 1, "WARN->GOOD": 1
    }
    assert report["new_bad_examples"] == ["seed.example"]
    assert second["hosts"]["seed.example"]["failed_observations"] == 1
    assert second["hosts"]["warn.example"] == {
        "status": "GOOD", "since_at": "2026-11-17T00:00:00+00:00"
    }

    third, report3 = make_health_report(tmp_path, second, "2026-11-18T00:00:00+00:00")
    assert report3["transitions"] == {}
    assert third["hosts"]["seed.example"]["failed_observations"] == 2
    fourth, report4 = make_health_report(tmp_path, third, "2026-11-19T00:00:00+00:00")
    assert fourth["hosts"]["seed.example"]["failed_observations"] == 3
    assert report4["failed_three_or_more_observations"] == 1


def test_new_and_removed_hosts_are_separate_from_transitions(tmp_path):
    write_data(tmp_path, ok=[good("seed.example")], bad=[])
    old, _ = make_health_report(tmp_path, None, "2026-11-16T00:00:00+00:00")
    write_data(tmp_path, ok=[good("seed.example"), good("new.example")], bad=[],
               monitored=["seed.example", "new.example"])
    _, report = make_health_report(tmp_path, old, "2026-11-17T00:00:00+00:00")
    assert report["new_hosts"] == 1
    assert report["removed_hosts"] == 3
    assert report["transitions"] == {}


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("nodeinfo: NameResolutionError('Failed to resolve')", "DNS"),
        ("nodeinfo: SSL certificate_verify_failed", "TLS"),
        ("nodeinfo: HTTP 429 from https://test.example", "HTTP_429"),
        ("nodeinfo: HTTP 404 from https://test.example", "HTTP_4XX"),
        ("nodeinfo: HTTP 503 from https://test.example", "HTTP_5XX"),
        ("nodeinfo: redirected to different host", "REDIRECT"),
        ("nodeinfo: unexpected Content-Type: text/html", "INVALID_RESPONSE"),
        ("terminal software marker: ap-tombstone", "TERMINAL"),
        ("classified as anomalous/invalid", "ANOMALOUS"),
    ],
)
def test_failure_reason_groups(reason, expected):
    assert reason_code({"last_failure_reason": reason}) == expected


def test_duplicate_observation_is_rejected(tmp_path):
    write_data(tmp_path, ok=[good("seed.example")], bad=[bad("seed.example")])
    with pytest.raises(ValueError, match="unexpected/duplicate"):
        make_health_report(tmp_path, None, "2026-11-16T00:00:00+00:00")


def test_corrupt_previous_snapshot_fails_instead_of_resetting(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text('{"schema_version": 9, "hosts": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported previous"):
        load_previous(path)
