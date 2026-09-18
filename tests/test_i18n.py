from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from scripts import fetch_stats


ROOT = Path(__file__).resolve().parents[1]
STRINGS_PATH = ROOT / "i18n" / "strings.json"

# These non-standard codes have been observed in real Fediverse instance data.
# Keep display labels for them even when a standards-based equivalent exists.
OBSERVED_COMPAT_LANGUAGE_CODES = {"vn", "cz"}


def load_strings() -> Dict[str, Dict[str, str]]:
    data = json.loads(STRINGS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def language_label_keys(strings: Dict[str, str]) -> set[str]:
    return {key for key in strings if key.startswith("language_name_")}


def test_all_canonical_language_codes_have_display_labels() -> None:
    strings = load_strings()
    required_codes = set(fetch_stats.LANG_CANON.values()) | OBSERVED_COMPAT_LANGUAGE_CODES

    for locale, translations in strings.items():
        missing = {
            code
            for code in required_codes
            if f"language_name_{code}" not in translations
        }
        assert not missing, (
            f"{locale} is missing language labels required by the collector "
            f"or compatibility layer: {sorted(missing)}"
        )


def test_locales_expose_the_same_language_label_keys() -> None:
    strings = load_strings()
    assert "ko" in strings

    reference_keys = language_label_keys(strings["ko"])

    for locale, translations in strings.items():
        locale_keys = language_label_keys(translations)
        missing = reference_keys - locale_keys
        extra = locale_keys - reference_keys

        assert not missing and not extra, (
            f"{locale} language label keys differ from ko; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
