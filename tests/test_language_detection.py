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
        (
            "一个安静的毛象花园。 A quiet garden where everyone can rest and relax.",
            ["zh", "en"],
        ),
        (
            "Nothing happened. 2026年9月13日 ActivityPub Test 2026年9月13日",
            ["en"],
        ),
        (
            "欢迎来到しいなカフェ！推荐语言：中文、日本語。",
            ["ja", "zh"],
        ),
        (
            "Լիլիթ Սյունեցիի անկապ մտքերը",
            ["hy"],
        ),
        (
            "ეს არის ქართული სოციალური სერვერი",
            ["ka"],
        ),
        (
            "Ἑλληνική κοινότητα για όλους",
            ["el"],
        ),
        (
            "Δρομογράφος και φίλοι. A community for independent reporting.",
            ["el", "en"],
        ),
        (
            "Δρομογράφος and friends server",
            ["el"],
        ),
        (
            "Masakit sa ulo ang mag-isip",
            ["tl"],
        ),
        (
            "See on Eestis mõeldud üldkasutatav server.",
            ["et"],
        ),
        (
            "'n Bediener waar mens net lekker kan gesels.",
            ["af"],
        ),
        (
            "Kani waa adeeg bulsho oo xor ah.",
            ["so"],
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
        "Green Web Hosting",
        "A minimalist ActivityPub server",
        "woxwoxwoxwoxwoxwoxwoxwoxwoxwoxwoxwox",
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


def test_japanese_old_orthography_is_not_treated_as_mixed_chinese() -> None:
    description = "聯合宇宙の片隅ひそり、嵐離れし星のあらはれ。"

    assert fetch_stats.detect_languages_from_text(description) == ["ja"]


def test_korean_hanja_definition_is_not_treated_as_mixed_chinese() -> None:
    description = "錄音은 소리를 기록하는 것을 뜻하는 한국어 설명입니다."

    assert fetch_stats.detect_languages_from_text(description) == ["ko"]


def test_fediverse_product_names_do_not_create_english_evidence() -> None:
    description = "这里是Iceshrimp实例，支持ActivityPub并与Mastodon和Misskey站点往来。"

    assert fetch_stats.detect_languages_from_text(description) == ["zh"]


@pytest.mark.parametrize("value", ["cs", "cz", "cs-CZ"])
def test_czech_language_codes_use_the_iso_639_1_code(value: str) -> None:
    assert fetch_stats.normalize_language_code(value) == "cs"


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
    assert record["languages_declared"] == []
    assert record["languages_inferred"] == ["ja"]
    assert record["languages_document"] == ["en"]
    assert record["language_detection_status"] == "current"


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
    assert record["languages_declared"] == []
    assert record["languages_inferred"] == []
    assert record["languages_document"] == ["zh"]


def test_legacy_record_is_reclassified_from_stored_description() -> None:
    record = {
        "host": "catpost.example",
        "languages_detected": ["ja", "en", "ca", "it"],
        "nodeinfo_description": "这里是catpost，玩得愉快！",
    }

    assert fetch_stats.upgrade_language_metadata(record)
    assert record["languages_detected"] == ["zh"]
    assert record["languages_declared"] == []
    assert record["languages_inferred"] == ["zh"]
    assert record["language_detection_status"] == "reclassified"


def test_ambiguous_legacy_record_preserves_old_value_for_review() -> None:
    record = {
        "host": "ambiguous.example",
        "languages_detected": ["ja", "ko"],
        "nodeinfo_description": "人文 · 科技 · 生活",
    }

    assert fetch_stats.upgrade_language_metadata(record)
    assert record["languages_detected"] == ["ja", "ko"]
    assert record["languages_inferred"] == []
    assert record["language_detection_status"] == "legacy_fallback"


def test_manual_language_override_wins_during_legacy_upgrade() -> None:
    record = {
        "host": "override.example",
        "languages_detected": ["ja"],
        "nodeinfo_description": "人文 · 科技 · 生活",
    }

    assert fetch_stats.upgrade_language_metadata(
        record,
        {"languages_detected": ["zh-TW"]},
    )
    assert record["languages_detected"] == ["zh"]
    assert record["languages_overridden"] == ["zh"]
    assert record["language_detection_status"] == "manual_override"


def test_version_upgrade_preserves_declared_language_evidence() -> None:
    record = {
        "host": "declared.example",
        "languages_detected": ["fr"],
        "languages_declared": ["fr"],
        "languages_inferred": [],
        "languages_document": [],
        "languages_overridden": [],
        "language_detection_version": 1,
        "language_detection_status": "current",
    }

    assert fetch_stats.upgrade_language_metadata(record)
    assert record["languages_detected"] == ["fr"]
    assert record["languages_declared"] == ["fr"]
    assert record["language_detection_status"] == "reclassified"
