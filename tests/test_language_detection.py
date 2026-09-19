from __future__ import annotations

import pytest

from scripts import fetch_stats


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "0fff.top 是联邦宇宙实例，基于开源平台 Misskey 运行。",
            ["zh"],
        ),
        ("一个中文长毛象(Mastodon)实例。", ["zh"]),
        ("日常生活紀錄", ["zh"]),
        (
            "Concrntはあなたの世界をちょっとだけより豊かにする、新しい時代のSNSです",
            ["ja"],
        ),
        ("한국어 인스턴스입니다", ["ko"]),
        (
            "This is a friendly Mastodon server for artists and local communities.",
            ["en"],
        ),
        ("You know the drill.", ["en"]),
        (
            "Bienvenue sur notre instance Mastodon francophone, ouverte et conviviale.",
            ["fr"],
        ),
        (
            "Esta es una instancia de Mastodon para nuestra comunidad local.",
            ["es"],
        ),
        (
            "Bem-vindo à nossa instância Mastodon para a comunidade local.",
            ["pt"],
        ),
        (
            "Willkommen auf unserer freundlichen Mastodon-Instanz für die lokale Gemeinschaft.",
            ["de"],
        ),
        ("Persönliches Blog", ["de"]),
        (
            "Это дружелюбный сервер Mastodon для местного сообщества и открытых обсуждений.",
            ["ru"],
        ),
        (
            "هذه خادومة ماستودون ودية للمجتمع المحلي والنقاشات العامة.",
            ["ar"],
        ),
        (
            "นี่คือเซิร์ฟเวอร์มาสโตดอนที่เป็นมิตรสำหรับชุมชนท้องถิ่นและการสนทนาทั่วไป",
            ["th"],
        ),
    ],
)
def test_detect_languages_from_description(
    description: str, expected: list[str]
) -> None:
    assert fetch_stats.detect_languages_from_text(description) == expected


@pytest.mark.parametrize(
    "description",
    [
        "Mastodon",
        "Misskey Server",
        "A solo mastodon server.",
        "private queer instance",
        "人文 · 科技 · 生活",
    ],
)
def test_short_or_ambiguous_descriptions_are_not_guessed(
    description: str,
) -> None:
    assert fetch_stats.detect_languages_from_text(description) == []


def test_language_detection_removes_markup_and_machine_readable_tokens() -> None:
    description = (
        '<p>Bienvenue sur <a href="https://example.social/about">notre instance</a>. '
        "Contact: @admin@example.social</p>"
    )

    cleaned = fetch_stats.clean_language_detection_text(description)

    assert "<p>" not in cleaned
    assert "https://" not in cleaned
    assert "@admin" not in cleaned
    assert fetch_stats.detect_languages_from_text(description) == ["fr"]


def test_han_alone_is_not_treated_as_japanese() -> None:
    assert fetch_stats.detect_scripts("人文 · 科技 · 生活") == []


def test_japanese_text_that_mentions_china_is_not_marked_chinese() -> None:
    description = "中国地方について話す日本語のコミュニティです。"

    assert fetch_stats.detect_languages_from_text(description) == ["ja"]


def test_conflicting_html_language_is_ignored_when_description_is_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetch_stats, "fetch_nodeinfo", lambda host: (None, None))
    monkeypatch.setattr(
        fetch_stats,
        "fetch_instance_details",
        lambda base_url, host: {
            "description": "これは日本語のインスタンスです。",
            "languages": ["en"],
        },
    )

    record, errors, _ = fetch_stats.process_instance(
        fetch_stats.Instance(
            name="Example",
            host="example.social",
            url="https://example.social",
            platform="unknown",
        ),
        "2026-09-19T00:00:00Z",
    )

    assert errors == []
    assert record["languages_detected"] == ["ja"]


def test_html_language_is_fallback_for_an_ambiguous_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetch_stats, "fetch_nodeinfo", lambda host: (None, None))
    monkeypatch.setattr(
        fetch_stats,
        "fetch_instance_details",
        lambda base_url, host: {
            "description": "人文 · 科技 · 生活",
            "languages": ["zh-TW"],
        },
    )

    record, errors, _ = fetch_stats.process_instance(
        fetch_stats.Instance(
            name="Example",
            host="example.social",
            url="https://example.social",
            platform="unknown",
        ),
        "2026-09-19T00:00:00Z",
    )

    assert errors == []
    assert record["languages_detected"] == ["zh"]
