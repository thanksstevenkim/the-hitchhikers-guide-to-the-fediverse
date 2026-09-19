from __future__ import annotations

from scripts import build_language_review_queue


def make_record(
    host: str,
    *,
    status: str,
    detected: list[str],
    declared: list[str],
    inferred: list[str],
    description: str,
) -> dict:
    return {
        "host": host,
        "software": {"name": "example"},
        "fetched_at": "2026-09-19T00:00:00Z",
        "languages_detected": detected,
        "languages_declared": declared,
        "languages_inferred": inferred,
        "language_detection_status": status,
        "nodeinfo_description": description,
    }


def test_review_queue_focuses_on_conflicts_and_legacy_fallbacks() -> None:
    stats = [
        make_record(
            "conflict.example",
            status="current",
            detected=["zh", "ja"],
            declared=["ja"],
            inferred=["zh"],
            description="这里是中文实例。",
        ),
        make_record(
            "legacy.example",
            status="legacy_fallback",
            detected=["ja", "ko"],
            declared=[],
            inferred=[],
            description="人文 · 科技 · 生活",
        ),
        make_record(
            "clean.example",
            status="current",
            detected=["en"],
            declared=["en"],
            inferred=["en"],
            description="This is a friendly community server.",
        ),
    ]

    queue = build_language_review_queue.build_review_queue(stats, {})

    assert queue["instance_count"] == 2
    by_host = {item["host"]: item for item in queue["instances"]}
    assert by_host["conflict.example"]["reasons"] == [
        "declared_inferred_conflict"
    ]
    assert by_host["legacy.example"]["reasons"] == [
        "ambiguous_han_only",
    ]

    queue_with_legacy = build_language_review_queue.build_review_queue(
        stats,
        {},
        include_legacy=True,
    )
    by_host_with_legacy = {
        item["host"]: item for item in queue_with_legacy["instances"]
    }
    assert by_host_with_legacy["legacy.example"]["reasons"] == [
        "legacy_fallback",
        "ambiguous_han_only",
    ]


def test_manual_override_removes_host_from_review_queue() -> None:
    stats = [
        make_record(
            "reviewed.example",
            status="legacy_fallback",
            detected=["zh"],
            declared=[],
            inferred=[],
            description="人文 · 科技 · 生活",
        )
    ]

    queue = build_language_review_queue.build_review_queue(
        stats,
        {"reviewed.example": {"languages_detected": ["zh"]}},
    )

    assert queue["instance_count"] == 0


def test_review_queue_flags_mixed_chinese_and_distinctive_script_gaps() -> None:
    stats = [
        make_record(
            "mixed.example",
            status="current",
            detected=["ja"],
            declared=[],
            inferred=["ja"],
            description="欢迎来到しいなカフェ！推荐语言：中文、日本語。",
        ),
        make_record(
            "armenian.example",
            status="current",
            detected=["et"],
            declared=[],
            inferred=["et"],
            description="Լիլիթ Սյունեցիի անկապ մտքերը",
        ),
    ]

    queue = build_language_review_queue.build_review_queue(stats, {})

    by_host = {item["host"]: item for item in queue["instances"]}
    assert by_host["mixed.example"]["reasons"] == [
        "strong_chinese_signal_missing"
    ]
    assert by_host["armenian.example"]["reasons"] == [
        "distinctive_script_missing"
    ]
