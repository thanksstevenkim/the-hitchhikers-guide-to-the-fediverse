#!/usr/bin/env python3
"""
Fetch Fediverse instance statistics with ActivityPub verification.

- Incremental save: after EACH instance is processed, results are saved atomically.
- Split outputs:
    * data/stats.ok.json  : verified + sane stats
    * data/stats.bad.json : failed verification, network/parse errors, or anomalous metrics
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse, urljoin
import codecs
from langdetect import detect_langs, LangDetectException
from html.parser import HTMLParser

TIMEOUT = 5
USER_AGENT = "fedlist-stats-fetcher/1.0"
FAILURE_THRESHOLD = 3
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Inputs
INSTANCES_PATH = DATA_DIR / "instances.json"
MONITORED_PATH = DATA_DIR / "monitored_instances.json"

LANG_CANON = {
    # 영어
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "eng": "en",
    "english-EN": "en",

    # 한국어
    "ko": "ko",
    "kr": "ko",
    "ko-kr": "ko",
    "korean": "ko",
    "korean-KO": "ko",
    "한국어": "ko",
    "조선어": "ko",

    # 일본어
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    "日本語": "ja",

    # 중국어 (필요하면 더 세분화)
    "zh": "zh",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "chinese": "zh",
    "中文": "zh",
    "cn": "zh",

    "pt": "pt",
    "pt-br": "pt",
    "portuguese": "pt",
    "portugu-S": "pt",

    "bn-BD": "bn",
    "german": "de",
    "de": "de",
    "deutsch": "de",
    "ger": "de",
    "fr": "fr",
    "french": "fr",
    "french-FR": "fr",
    "fren": "fr",
    "polish": "pl",
    "pl": "pl",
    "dk": "da",
    "spanish": "es",
    "sp": "es",
    "cs": "cz",
    "mm": "my",
    "rs": "sr",
}

# Outputs (split)
ALIASES_PATH = DATA_DIR / "host_aliases.json"
STATS_OK_PATH  = DATA_DIR / "stats.ok.json"
STATS_BAD_PATH = DATA_DIR / "stats.bad.json"

# (Legacy) Single-file path retained for compatibility in helper logic
STATS_PATH = DATA_DIR / "stats.json"

MANUAL_OVERRIDES_PATH = DATA_DIR / "manual_overrides.json"


def configure_data_dir(data_dir: Path) -> None:
    """Point all data inputs and outputs at one directory.

    GitHub Actions uses this to collect into a staging directory. The tracked
    site data is only replaced after the staged files pass validation.
    """
    global DATA_DIR, INSTANCES_PATH, MONITORED_PATH, ALIASES_PATH
    global STATS_OK_PATH, STATS_BAD_PATH, STATS_PATH, MANUAL_OVERRIDES_PATH

    DATA_DIR = data_dir.resolve()
    INSTANCES_PATH = DATA_DIR / "instances.json"
    MONITORED_PATH = DATA_DIR / "monitored_instances.json"
    ALIASES_PATH = DATA_DIR / "host_aliases.json"
    STATS_OK_PATH = DATA_DIR / "stats.ok.json"
    STATS_BAD_PATH = DATA_DIR / "stats.bad.json"
    STATS_PATH = DATA_DIR / "stats.json"
    MANUAL_OVERRIDES_PATH = DATA_DIR / "manual_overrides.json"

# Network safety limits
MAX_JSON_BYTES = 2_000_000  # 2MB soft cap for JSON payloads
MAX_REDIRECTS = 5
ALLOWED_JSON_CT = ("application/json", "application/ld+json", "application/activity+json")
BLOCKED_SUFFIXES = (".bin", ".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".mp4", ".mp3", ".avi")

try:  # Optional dependency, falls back to urllib if unavailable
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional import guard
    requests = None


@dataclass
class Instance:
    name: str
    host: str
    url: str
    platform: str


class FetchError(RuntimeError):
    """Raised when a remote fetch fails."""


def _same_host(url: str, host: str) -> bool:
    try:
        h = urlparse(url).hostname
        return (h or "").lower() == host.lower()
    except Exception:
        return False


def _looks_like_binary(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(suf) for suf in BLOCKED_SUFFIXES)


def looks_like_nodeinfo(doc: Any) -> bool:
    """
    최소 요건:
      - dict여야 함
      - software.name 존재
      - version이 문자열(권장) — 일부 서버는 숫자도 주므로 관대하게 처리
      - (선택) protocols가 list면 문자열 요소들
    """
    if not isinstance(doc, dict):
        return False
    sw = doc.get("software")
    if not isinstance(sw, dict):
        return False
    name = sw.get("name")
    if not isinstance(name, str) or not name.strip():
        return False

    ver = doc.get("version")
    if ver is None:
        # 버전 없이 배포되는 케이스가 드물게 있으므로 관대 승
        return True
    if isinstance(ver, (str, int, float)):
        return True
    return False

def _assert_safe_url(url: str, host: str) -> None:
    # 동일 호스트 아니거나, 의심 확장자면 차단
    if not _same_host(url, host):
        raise FetchError(f"redirected to different host: {url}")
    if _looks_like_binary(url):
        raise FetchError(f"suspicious path: {url}")

def _is_json_ct(content_type: str) -> bool:
    if not content_type:
        return False
    ct = content_type.split(";")[0].strip().lower()
    # 표준 JSON 또는 +json 파생 타입 허용
    return ct == "application/json" or ct.endswith("+json")

def _normalize_host(h: str) -> str:
    # 포트 제거 (IPv4/도메인에만 적용, IPv6는 대괄호 표기 가정)
    raw = (h or "").strip()
    if raw.startswith("["):  # [::1]:8443 형태는 그대로 두되 대괄호 제거만
        # [::1]:8443 → ::1]:8443 → 간단 처리 어려우면 일단 전체를 IDNA 처리만
        host = raw
    else:
        # 도메인/IPv4: 마지막 콜론 뒤가 숫자면 포트로 보고 제거
        if ":" in raw:
            head, tail = raw.rsplit(":", 1)
            if tail.isdigit():
                raw = head
        host = raw
    try:
        return host.encode("idna").decode("ascii").lower().rstrip(".")
    except Exception:
        return host.lower().rstrip(".")


def _same_zone(a: str, b: str) -> bool:
    """
    같은 eTLD+1(대략적)인지 판정.
    - 정확한 PSL 라이브러리 없이, 실무용 휴리스틱:
      서로 같거나, 한쪽이 다른쪽의 서브도메인인 경우 허용.
      (예: example.org ↔ mastodon.example.org)
    """
    if not a or not b:
        return False
    a = _normalize_host(a)
    b = _normalize_host(b)
    if a == b:
        return True
    return a.endswith("." + b) or b.endswith("." + a)

def _assert_safe_url_relaxed(url: str, expected_host: str) -> None:
    """
    '같은 존'까지 허용하는 안전 검사:
    - 다른 존으로의 리다이렉트/링크는 차단
    - 의심 확장자 차단은 그대로 유지
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip()
    if not _same_zone(host, expected_host):
        raise FetchError(f"redirected to different host: {url}")
    if _looks_like_binary(url):
        raise FetchError(f"suspicious path: {url}")

def _sanitize_charset(enc: Optional[str]) -> str:
    """
    잘못된 charset 헤더 방어:
    - None/빈값 → 'utf-8'
    - 콤마/슬래시/공백 등 섞인 비정상 값 → 'utf-8'
    - codecs.lookup 실패 → 'utf-8'
    """
    if not enc:
        return "utf-8"
    s = str(enc).strip().strip('"').lower()
    # 흔한 쓰레기 패턴 방어: "utf-8, application/json" 等
    if any(ch in s for ch in (",", "/", " ", "\t", ";")) and s != "utf-8":
        return "utf-8"
    try:
        codecs.lookup(s)
        return s
    except LookupError:
        return "utf-8"

def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    configure_data_dir(Path(args.data_dir))

    aliases = load_aliases()
    seed_instances = list(load_instances(INSTANCES_PATH))
    ok_map, bad_map = load_existing_stats_maps()
    monitored, registry_changed = prepare_monitored_registry(
        seed_instances,
        ok_map,
        aliases,
    )
    if registry_changed:
        save_monitored_registry_atomic(monitored, aliases)

    # Candidate inputs are a queue of unseen hosts. The default path is a
    # refresh of the complete persistent monitoring set, not just the seeds.
    if args.input:
        instances = list(load_host_strings(Path(args.input)))
    else:
        instances = monitored_instances(monitored, aliases)

    if not instances:
        if args.input:
            logging.info("No new candidate instances to process.")
        else:
            logging.error(
                "No instances to process. Populate data/instances.json or "
                "data/monitored_instances.json."
            )
        return

    # 현재 UTC 타임스탬프 (ISO8601, Z)
    now = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    manual_overrides = load_manual_overrides()

    discovered_hosts: Set[str] = set()
    processed = 0
    updated_ok = 0
    updated_bad = 0

    for instance in instances:
        try:
            # 1) 인스턴스에서 raw record 뽑기
            record, errors, peers = process_instance(instance, now)
        except Exception as exc:
            logging.exception("FATAL while processing %s", instance.host)
            # 2) 최소 레코드로 대체
            record = {
                "host": instance.host,
                "verified_activitypub": False,
                "software": {},
                "open_registrations": None,
                "users_total": None,
                "users_active_month": None,
                "statuses": None,
                "languages_detected": [],
                "fetched_at": now,
            }
            errors = [f"fatal: {exc!r}"]
            peers = set()

        # 3) 무조건 여기서 manual_overrides 적용 (정상/예외 둘 다)
        apply_manual_overrides(record, manual_overrides)

        # 4) 그 결과를 기준으로 분류하고 상호 배타적인 상태로 저장
        current_aliases = load_aliases()
        had_errors = bool(errors)
        bucket = classify_record(record, had_errors)  # 'good' or 'bad'
        reason = "; ".join(errors) if errors else "classified as anomalous/invalid"
        state, ok_changed, bad_changed, failure_count = apply_health_transition(
            record,
            bucket,
            ok_map,
            bad_map,
            current_aliases,
            failure_reason=reason,
        )

        # Monitoring membership is independent of display health. Existing
        # monitored instances remain registered on failure; reviewed
        # candidates join only after a successful collection.
        if not args.input or state == "good":
            software = record.get("software")
            platform = (
                str(software.get("name", "")).strip().lower()
                if isinstance(software, dict)
                else ""
            )
            registry_changed = register_monitored_instance(
                monitored,
                Instance(
                    name=instance.name or record["host"],
                    host=record["host"],
                    url=instance.url,
                    platform=platform or instance.platform,
                ),
                source="peer" if args.input else monitored_source_for(
                    monitored, instance.host, current_aliases
                ),
                aliases=current_aliases,
            )
            if registry_changed:
                save_monitored_registry_atomic(monitored, current_aliases)
        updated_ok += int(ok_changed)
        updated_bad += int(bad_changed)

        if state == "good":
            logging.info(
                "OK   %s (%s)",
                record["host"],
                record.get("software", {}).get("name") or "-",
            )
        elif state == "transient_failure":
            logging.warning(
                "WARN %s: transient failure %d/%d; retaining last known good stats: %s",
                record["host"],
                failure_count,
                FAILURE_THRESHOLD,
                reason,
            )
        else:
            logging.warning(
                "BAD  %s (consecutive failures=%d): %s",
                record["host"],
                failure_count,
                reason,
            )

        processed += 1
        save_stats_pair_atomic(ok_map, bad_map, current_aliases)

        if args.discover_peers and peers:
            discovered_hosts.update(peers)

        logging.info(
            "Incremental save complete: processed=%d, ok_updates=%d, bad_updates=%d",
            processed, updated_ok, updated_bad
        )

    if args.discover_peers:
        # Load the known set once; do not repeatedly parse JSON in this loop.
        checked_hosts = load_checked_hosts()

        suggestions = sorted(
            h for h in discovered_hosts if h not in checked_hosts
        )
        peer_output = args.peer_output or str(DATA_DIR / "peer_suggestions.json")
        emit_peer_suggestions(suggestions, peer_output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch ActivityPub stats (incremental save, split outputs).")
    parser.add_argument(
        "--data-dir",
        default=str(DATA_DIR),
        help="Directory containing inputs and receiving outputs (default: data)."
    )
    parser.add_argument(
        "--input",
        help="Input JSON file with host list (plain strings or objects). Results merge into stats.ok/bad.json."
    )
    parser.add_argument(
        "--discover-peers",
        action="store_true",
        help="Attempt to gather federation peers for later curation."
    )
    parser.add_argument(
        "--peer-output",
        default=None,
        help="File path for discovered peers (default: <data-dir>/peer_suggestions.json; use '-' for stdout)."
    )
    return parser.parse_args()


# -------------------------------
# Saving & loading (split files)
# -------------------------------

def load_aliases() -> Dict[str, str]:
    """
    원본호스트 -> 캐노니컬호스트 매핑.
    예: {"0xcb.dev": "mastodon.0xcb.dev"}
    """
    if not ALIASES_PATH.exists():
        return {}
    try:
        data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # 키/값 모두 정규화
            out: Dict[str, str] = {}
            for k, v in data.items():
                nk = _normalize_host(k)
                nv = _normalize_host(v)
                if nk and nv:
                    out[nk] = nv
            return out
    except Exception:
        pass
    return {}


def resolve_canonical_host(host: str, aliases: Dict[str, str]) -> str:
    """Resolve a normalized host through alias chains without looping."""
    current = _normalize_host(host)
    seen: Set[str] = set()
    while current:
        if current in seen:
            return min(seen)
        seen.add(current)
        target = _normalize_host(aliases.get(current, ""))
        if not target or target == current:
            break
        current = target
    return current


MONITORED_SOURCE_PRIORITY = {"legacy": 0, "peer": 1, "seed": 2}


def _monitored_entry_as_instance(entry: Dict[str, Any]) -> Instance:
    host = _normalize_host(str(entry.get("host", "")))
    return Instance(
        name=str(entry.get("name", "")).strip() or host,
        host=host,
        url=str(entry.get("url", "")).strip() or f"https://{host}",
        platform=str(entry.get("platform", "")).strip().lower() or "unknown",
    )


def monitored_source_for(
    registry: Dict[str, Dict[str, Any]],
    host: str,
    aliases: Dict[str, str],
) -> str:
    """Return the preserved provenance for one canonical monitored host."""
    canonical_host = resolve_canonical_host(host, aliases)
    entry = registry.get(canonical_host)
    if entry is not None:
        source = str(entry.get("source", "legacy"))
        return source if source in MONITORED_SOURCE_PRIORITY else "legacy"
    return "legacy"


def register_monitored_instance(
    registry: Dict[str, Dict[str, Any]],
    instance: Instance,
    *,
    source: str,
    aliases: Dict[str, str],
) -> bool:
    """Insert or canonicalize an instance without ever dropping membership."""
    canonical_host = resolve_canonical_host(instance.host, aliases)
    if not canonical_host:
        return False
    source = source if source in MONITORED_SOURCE_PRIORITY else "legacy"

    # Registry keys are canonicalized on load and save, so insertion and
    # alias collapse stay O(1) even for tens of thousands of monitored hosts.
    existing = registry.pop(canonical_host, {})
    existing_source = str(existing.get("source", "legacy"))
    if MONITORED_SOURCE_PRIORITY.get(existing_source, 0) > MONITORED_SOURCE_PRIORITY[source]:
        source = existing_source

    parsed_url_host = _normalize_host(urlparse(instance.url).hostname or "")
    url = (
        normalize_base_url(instance.url, canonical_host)
        if resolve_canonical_host(parsed_url_host, aliases) == canonical_host
        else f"https://{canonical_host}"
    )
    name = instance.name.strip() or str(existing.get("name", "")).strip() or canonical_host
    platform = instance.platform.strip().lower()
    if not platform or platform == "unknown":
        platform = str(existing.get("platform", "")).strip().lower() or "unknown"

    updated: Dict[str, Any] = {
        "host": canonical_host,
        "url": url,
        "source": source,
    }
    if name != canonical_host:
        updated["name"] = name
    if platform != "unknown":
        updated["platform"] = platform

    changed = existing != updated
    registry[canonical_host] = updated
    return changed


def load_monitored_registry(
    aliases: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Load the persistent health-check set, accepting legacy string rows."""
    aliases = aliases if aliases is not None else load_aliases()
    if not MONITORED_PATH.exists():
        return {}
    try:
        rows = json.loads(MONITORED_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.warning("Could not load %s: %s", MONITORED_PATH.name, exc)
        return {}
    if not isinstance(rows, list):
        logging.warning("%s must be a JSON array", MONITORED_PATH.name)
        return {}

    registry: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, str):
            host = _normalize_host(row)
            entry: Dict[str, Any] = {"host": host, "source": "legacy"}
        elif isinstance(row, dict):
            entry = row
            host = _normalize_host(str(row.get("host", "")))
        else:
            continue
        if not host:
            continue
        register_monitored_instance(
            registry,
            Instance(
                name=str(entry.get("name", "")).strip() or host,
                host=host,
                url=str(entry.get("url", "")).strip() or f"https://{host}",
                platform=str(entry.get("platform", "")).strip().lower() or "unknown",
            ),
            source=str(entry.get("source", "legacy")),
            aliases=aliases,
        )
    return registry


def prepare_monitored_registry(
    seed_instances: Sequence[Instance],
    ok_map: Dict[str, Dict[str, Any]],
    aliases: Dict[str, str],
) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """Load/migrate registry and enforce seeds + current OK as members."""
    registry = load_monitored_registry(aliases)
    started_empty = not registry
    changed = False

    for instance in seed_instances:
        changed |= register_monitored_instance(
            registry, instance, source="seed", aliases=aliases
        )

    for record in ok_map.values():
        host = _normalize_host(str(record.get("host", "")))
        if not host:
            continue
        software = record.get("software")
        platform = (
            str(software.get("name", "")).strip().lower()
            if isinstance(software, dict)
            else "unknown"
        )
        changed |= register_monitored_instance(
            registry,
            Instance(host, host, f"https://{host}", platform or "unknown"),
            source="legacy",
            aliases=aliases,
        )

    if started_empty and registry:
        logging.info(
            "Bootstrapped %s from instances.json and stats.ok.json",
            MONITORED_PATH.name,
        )
    return registry, changed


def monitored_instances(
    registry: Dict[str, Dict[str, Any]],
    aliases: Dict[str, str],
) -> List[Instance]:
    """Return one canonical health-check target for every registry member."""
    canonical: Dict[str, Dict[str, Any]] = {}
    for entry in registry.values():
        instance = _monitored_entry_as_instance(entry)
        register_monitored_instance(
            canonical,
            instance,
            source=str(entry.get("source", "legacy")),
            aliases=aliases,
        )
    return [_monitored_entry_as_instance(canonical[host]) for host in sorted(canonical)]


def save_monitored_registry_atomic(
    registry: Dict[str, Dict[str, Any]],
    aliases: Optional[Dict[str, str]] = None,
) -> None:
    """Canonicalize and atomically persist the long-lived monitoring set."""
    aliases = aliases if aliases is not None else load_aliases()
    canonical: Dict[str, Dict[str, Any]] = {}
    for entry in registry.values():
        register_monitored_instance(
            canonical,
            _monitored_entry_as_instance(entry),
            source=str(entry.get("source", "legacy")),
            aliases=aliases,
        )
    registry.clear()
    registry.update(canonical)
    MONITORED_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MONITORED_PATH.with_suffix(MONITORED_PATH.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            [registry[host] for host in sorted(registry)],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(MONITORED_PATH)


def _pop_equivalent_records(
    records: Dict[str, Dict[str, Any]],
    canonical_host: str,
    aliases: Dict[str, str],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Remove and return every record resolving to one canonical host."""
    matches: List[Tuple[str, Dict[str, Any]]] = []
    for key, value in list(records.items()):
        record_host = value.get("host") if isinstance(value, dict) else key
        candidate_hosts = [str(record_host or key)]
        redirected_from = value.get("redirected_from") if isinstance(value, dict) else None
        if isinstance(redirected_from, str):
            candidate_hosts.append(redirected_from)
        elif isinstance(redirected_from, (list, tuple, set)):
            candidate_hosts.extend(str(host) for host in redirected_from)
        if any(
            resolve_canonical_host(candidate, aliases) == canonical_host
            for candidate in candidate_hosts
        ):
            matches.append((key, records.pop(key)))
    return matches


def _latest_record(
    records: Sequence[Tuple[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not records:
        return None
    return max(
        (record for _, record in records),
        key=lambda record: str(
            record.get("last_failure_at") or record.get("fetched_at") or ""
        ),
    )


def _failure_count(record: Optional[Dict[str, Any]]) -> int:
    if not record:
        return 0
    value = record.get("consecutive_failures", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def apply_health_transition(
    record: Dict[str, Any],
    bucket: str,
    ok_map: Dict[str, Dict[str, Any]],
    bad_map: Dict[str, Dict[str, Any]],
    aliases: Dict[str, str],
    *,
    failure_reason: str = "classified as anomalous/invalid",
    failure_threshold: int = FAILURE_THRESHOLD,
) -> Tuple[str, bool, bool, int]:
    """Apply one GOOD/BAD observation to mutually exclusive health maps.

    A previously healthy instance gets a grace period for transient failures.
    Hosts without a last-known-good record remain BAD immediately. All alias
    variants are removed before the canonical record is inserted.
    """
    if bucket not in {"good", "bad"}:
        raise ValueError(f"unsupported health bucket: {bucket}")
    if failure_threshold < 1:
        raise ValueError("failure_threshold must be at least 1")

    observed_host = _normalize_host(str(record.get("host", "")))
    canonical_host = resolve_canonical_host(observed_host, aliases)
    if not canonical_host:
        raise ValueError("health record requires a non-empty host")

    record["host"] = canonical_host
    current = dict(record)
    if observed_host != canonical_host and not current.get("redirected_from"):
        current["redirected_from"] = observed_host

    previous_ok_records = _pop_equivalent_records(ok_map, canonical_host, aliases)
    previous_bad_records = _pop_equivalent_records(bad_map, canonical_host, aliases)
    previous_ok = _latest_record(previous_ok_records)
    previous_bad = _latest_record(previous_bad_records)

    if bucket == "good":
        current["consecutive_failures"] = 0
        current.pop("last_failure_at", None)
        current.pop("last_failure_reason", None)
        ok_map[canonical_host] = current
        ok_changed = (
            previous_ok != current
            or len(previous_ok_records) != 1
            or previous_ok_records[0][0] != canonical_host
        )
        return "good", ok_changed, bool(previous_bad_records), 0

    prior_failure_count = _failure_count(previous_ok or previous_bad)
    failure_count = prior_failure_count + 1
    failure_at = str(current.get("fetched_at") or "")

    if previous_ok is not None and failure_count < failure_threshold:
        retained = dict(previous_ok)
        retained["host"] = canonical_host
        retained["consecutive_failures"] = failure_count
        retained["last_failure_at"] = failure_at
        retained["last_failure_reason"] = failure_reason
        ok_map[canonical_host] = retained
        ok_changed = (
            previous_ok != retained
            or len(previous_ok_records) != 1
            or previous_ok_records[0][0] != canonical_host
        )
        return "transient_failure", ok_changed, bool(previous_bad_records), failure_count

    current["consecutive_failures"] = failure_count
    current["last_failure_at"] = failure_at
    current["last_failure_reason"] = failure_reason
    bad_map[canonical_host] = current
    bad_changed = (
        previous_bad != current
        or len(previous_bad_records) != 1
        or previous_bad_records[0][0] != canonical_host
    )
    return "bad", bool(previous_ok_records), bad_changed, failure_count


def reconcile_health_maps(
    ok_map: Dict[str, Dict[str, Any]],
    bad_map: Dict[str, Dict[str, Any]],
    aliases: Dict[str, str],
) -> None:
    """Canonicalize both maps and repair legacy overlaps before every save.

    A persisted BAD record with enough consecutive failures wins an existing
    conflict. Otherwise the last-known-good record wins conservatively.
    """
    def _canonicalize(
        source: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        grouped: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
        for key, value in source.items():
            if not isinstance(value, dict):
                continue
            observed_host = _normalize_host(str(value.get("host") or key))
            canonical_host = resolve_canonical_host(observed_host, aliases)
            if not canonical_host:
                continue
            normalized = dict(value)
            normalized["host"] = canonical_host
            if observed_host != canonical_host and not normalized.get("redirected_from"):
                normalized["redirected_from"] = observed_host
            grouped.setdefault(canonical_host, []).append((key, normalized))

        result: Dict[str, Dict[str, Any]] = {}
        for canonical_host, candidates in grouped.items():
            selected = _latest_record(candidates)
            if selected is not None:
                result[canonical_host] = selected
        return result

    canonical_ok = _canonicalize(ok_map)
    canonical_bad = _canonicalize(bad_map)
    for host in canonical_ok.keys() & canonical_bad.keys():
        if _failure_count(canonical_bad[host]) >= FAILURE_THRESHOLD:
            canonical_ok.pop(host, None)
        else:
            canonical_bad.pop(host, None)

    ok_map.clear()
    ok_map.update(canonical_ok)
    bad_map.clear()
    bad_map.update(canonical_bad)

def save_aliases(aliases: Dict[str, str]) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 예쁘게 저장
    ALIASES_PATH.write_text(
        json.dumps(aliases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

def register_alias(original_host: str, canonical_host: str) -> None:
    """원본 → 캐노니컬 매핑을 추가/갱신."""
    aliases = load_aliases()
    o = _normalize_host(original_host)
    c = _normalize_host(canonical_host)
    if not o or not c or o == c:
        return
    # 서로 같은 존일 때만 기록(보수적으로)
    if not _same_zone(o, c):
        return
    # 이미 같은 값이면 스킵
    if aliases.get(o) == c:
        return
    aliases[o] = c
    save_aliases(aliases)

def load_existing_stats_maps() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Load existing OK/BAD stats from split files into host->record maps.
    """
    def _load(path: Path) -> Dict[str, Dict[str, Any]]:
        m: Dict[str, Dict[str, Any]] = {}
        if not path.exists():
            return m
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for e in data:
                    if isinstance(e, dict) and "host" in e:
                        m[e["host"]] = e
        except Exception as exc:
            logging.warning("Could not load %s: %s", path.name, exc)
        return m

    ok_map  = _load(STATS_OK_PATH)
    bad_map = _load(STATS_BAD_PATH)

    # (Optional) Legacy single-file import on first run if split files are missing
    if not ok_map and not bad_map and STATS_PATH.exists():
        try:
            data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for e in data:
                    if isinstance(e, dict) and "host" in e:
                        # naive split: verified goes to OK, others to BAD
                        (ok_map if e.get("verified_activitypub") else bad_map)[e["host"]] = e
            logging.info("Migrated legacy stats.json into split files (ok/bad).")
        except Exception as exc:
            logging.warning("Could not migrate legacy stats.json: %s", exc)

    return ok_map, bad_map


def save_stats_pair_atomic(
    ok_map: Dict[str, Dict[str, Any]],
    bad_map: Dict[str, Dict[str, Any]],
    aliases: Optional[Dict[str, str]] = None,
) -> None:
    """
    Write OK/BAD lists atomically to their respective files.
    """
    def _write_atomic(path: Path, items: List[Dict[str, Any]]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)  # atomic on same filesystem

    reconcile_health_maps(ok_map, bad_map, aliases if aliases is not None else load_aliases())

    ok_list  = sorted(ok_map .values(), key=lambda x: x.get("host", ""))
    bad_list = sorted(bad_map.values(), key=lambda x: x.get("host", ""))

    _write_atomic(STATS_OK_PATH,  ok_list)
    _write_atomic(STATS_BAD_PATH, bad_list)


def load_checked_hosts() -> Set[str]:
    checked: Set[str] = set()

    def _merge_from(path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for e in data:
                    if isinstance(e, dict):
                        h = e.get("host")
                        if isinstance(h, str) and h:
                            checked.add(_normalize_host(h))
                        rf = e.get("redirected_from")
                        if isinstance(rf, str) and rf:
                            checked.add(_normalize_host(rf))
                        elif isinstance(rf, (list, tuple, set)):
                            for x in rf:
                                if isinstance(x, str) and x:
                                    checked.add(_normalize_host(x))
        except Exception:
            pass

    _merge_from(STATS_OK_PATH)
    _merge_from(STATS_BAD_PATH)
    _merge_from(STATS_PATH)  # legacy
    _merge_from(MONITORED_PATH)

    # 별칭 파일도 병합 (원본 호스트는 사실상 검사된 것으로 간주)
    aliases = load_aliases()
    for src, dst in aliases.items():
        checked.add(_normalize_host(src))
        checked.add(_normalize_host(dst))

    return checked | {resolve_canonical_host(host, aliases) for host in checked}

def load_manual_overrides() -> Dict[str, Dict[str, Any]]:
    """
    data/manual_overrides.json 을 읽어서
    {host: { 필드: 값, ... }} 형태로 리턴.
    """
    if not MANUAL_OVERRIDES_PATH.exists():
        return {}

    try:
        raw = json.loads(MANUAL_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.warning("Could not load manual_overrides.json: %s", exc)
        return {}

    # dict 형태만 지원 ({"host": {...}, ...})
    if not isinstance(raw, dict):
        logging.warning("manual_overrides.json must be an object keyed by host.")
        return {}

    overrides: Dict[str, Dict[str, Any]] = {}
    for host, value in raw.items():
        if not isinstance(host, str) or not isinstance(value, dict):
            continue
        key = _normalize_host(host)
        if not key:
            continue
        overrides[key] = value
    return overrides


def apply_manual_overrides(record: Dict[str, Any],
                           overrides: Dict[str, Dict[str, Any]]) -> None:
    """
    하나의 레코드에 대해 manual_overrides 내용 강제 적용.
    - 최상위 필드는 그대로 덮어씀
    - software / languages_detected 는 약간 더 조심해서 처리
    """
    host = record.get("host")
    if not isinstance(host, str):
        return
    key = _normalize_host(host)
    if not key:
        return

    data = overrides.get(key)
    if not data:
        return

    for field, value in data.items():
        if field == "software" and isinstance(value, dict):
            # software.name / software.version 수동 수정 허용
            target = record.get("software")
            if not isinstance(target, dict):
                target = {}
                record["software"] = target
            if "name" in value and value["name"] is not None:
                target["name"] = str(value["name"])
            if "version" in value and value["version"] is not None:
                target["version"] = str(value["version"])

        elif field == "languages_detected":
            # 언어 코드는 normalize_language_code로 정규화
            if not isinstance(value, (list, tuple, set)):
                continue
            langs: List[str] = []
            seen: set = set()
            for v in value:
                code = normalize_language_code(v)
                if not code or code in seen:
                    continue
                seen.add(code)
                langs.append(code)
            record["languages_detected"] = langs

        else:
            # 그 외 필드는 그대로 덮어씀 (open_registrations, users_total 등)
            record[field] = value

# -------------------------------
# Classification (good vs bad)
# -------------------------------

def is_anomalous(record: Dict[str, Any]) -> bool:
    """
    Simple anomaly rules:
      - negative counters
      - absurd statuses per user ratio
    """
    u = record.get("users_total")
    s = record.get("statuses")
    am = record.get("users_active_month")

    try:
        if u is not None and u < 0:
            return True
        if s is not None and s < 0:
            return True
        if am is not None and am < 0:
            return True
        if u and s and u > 0 and (s / u) > 50000:
            return True
    except Exception:
        return True
    return False

def classify_record(record: Dict[str, Any], had_errors: bool) -> str:
   """
    정책 단순화:
      - NodeInfo가 '제대로' 있으면 OK
      - 단, 수치가 명백히 비정상이면 BAD
      - NodeInfo 자체가 없거나 실패하면 BAD
   """
   if not record.get("verified_activitypub"):
       return "bad"
   if is_anomalous(record):
       return "bad"
   return "good"

# -------------------------------
# Loading inputs
# -------------------------------

def load_instances(path: Path) -> Iterable[Instance]:
    """Load the curated seed instances that must be refreshed every run.

    Unlike ``load_host_strings()``, this loader intentionally does not filter
    hosts already present in the OK/BAD statistics. ``instances.json`` is the
    operator-maintained refresh set, not a queue of previously unseen hosts.
    Host aliases are still applied so collection uses the canonical endpoint.
    """
    if not path.exists():
        logging.error("Instances file not found: %s", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logging.error("Invalid JSON in %s: %s", path, exc)
        return []

    if not isinstance(data, list):
        logging.error("Expected a list in %s", path)
        return []
    
    aliases = load_aliases()

    instances: List[Instance] = []
    seen: Set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url", "")).strip()
        if not url:
            logging.warning("Skipping entry without URL: %s", entry)
            continue
        host = extract_host(entry)
        if not host:
            logging.warning("Skipping %s: could not determine host", url)
            continue

        mapped = resolve_canonical_host(host, aliases)
        if mapped in seen:
            continue
        seen.add(mapped)
        instances.append(
            Instance(
                name=str(entry.get("name", "")).strip() or mapped,
                host=mapped,
                url=(
                    normalize_base_url(url, mapped)
                    if resolve_canonical_host(
                        _normalize_host(urlparse(url).hostname or ""), aliases
                    ) == mapped
                    else f"https://{mapped}"
                ),
                platform=str(entry.get("platform", "")).strip().lower() or "unknown",
            )
        )
    logging.info("Loaded %d curated instances from %s", len(instances), format_relative(path))
    return instances


def load_host_strings(path: Path) -> Iterable[Instance]:
    """
    Load a candidate list of hosts given as strings or dict entries.

    This path is used for peer discovery follow-up and intentionally excludes
    hosts already checked in OK/BAD/legacy stats or represented by aliases.
    """
    if not path.exists():
        logging.error("Host list file not found: %s", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logging.error("Invalid JSON in %s: %s", path, exc)
        return []

    if not isinstance(data, list):
        logging.error("Expected a list in %s", path)
        return []

    checked_hosts = load_checked_hosts()
    aliases = load_aliases()
    skipped_count = 0
    instances: List[Instance] = []
    queued_hosts: Set[str] = set()

    for entry in data:
        if isinstance(entry, str):
            host = _normalize_host(entry)
            if not host:
                continue
            mapped = resolve_canonical_host(host, aliases)
            if mapped in checked_hosts or mapped in queued_hosts:
                skipped_count += 1
                continue
            queued_hosts.add(mapped)
            instances.append(
                Instance(
                    name=entry.strip() or mapped,
                    host=mapped,
                    url=f"https://{mapped}",
                    platform="unknown",
                )
            )
        elif isinstance(entry, dict):
            url = str(entry.get("url", "")).strip()
            host = extract_host(entry)
            if not host:
                logging.warning("Skipping %s: could not determine host", url)
                continue
            host = _normalize_host(host)

            mapped = resolve_canonical_host(host, aliases)
            if mapped in checked_hosts or mapped in queued_hosts:
                skipped_count += 1
                continue
            queued_hosts.add(mapped)
            instances.append(
                Instance(
                    name=str(entry.get("name", "")).strip() or mapped,
                    host=mapped,
                    url=(
                        normalize_base_url(url or f"https://{mapped}", mapped)
                        if resolve_canonical_host(
                            _normalize_host(urlparse(url).hostname or mapped), aliases
                        ) == mapped
                        else f"https://{mapped}"
                    ),
                    platform=str(entry.get("platform", "")).strip().lower() or "unknown",
                )
            )

    logging.info(
        "Loaded %d new hosts from %s (%d already checked, skipped)",
        len(instances), format_relative(path), skipped_count
    )
    return instances


# -------------------------------
# Fetching & parsing
# -------------------------------

def process_instance(instance: Instance, timestamp: str) -> Tuple[Dict[str, Any], List[str], Set[str]]:
    logging.info("BEGIN %s", instance.host)
    record: Dict[str, Any] = {
        "host": instance.host,
        "verified_activitypub": False,
        "software": {},
        "open_registrations": None,
        "users_total": None,
        "users_active_month": None,
        "statuses": None,
        "languages_detected": [],
        "fetched_at": timestamp,
    }
    errors: List[str] = []
    languages: List[str] = []
    languages_seen = set()
    peers: Set[str] = set()

    canonical_base: Optional[str] = None
    try:
        nodeinfo, canonical_base = fetch_nodeinfo(instance.host)
    except FetchError as exc:
        logging.warning("nodeinfo error for %s: %s", instance.host, exc)
        errors.append(f"nodeinfo: {exc}")
        nodeinfo = None

    if nodeinfo and looks_like_nodeinfo(nodeinfo):
        record["verified_activitypub"] = True
        update_software(record, nodeinfo.get("software", {}))
        update_open_registrations(record, nodeinfo.get("openRegistrations"))

        usage = nodeinfo.get("usage") if isinstance(nodeinfo, dict) else None
        users = usage.get("users") if isinstance(usage, dict) else None
        update_numeric(record, "users_total", coerce_int(users, "total"))
        update_numeric(record, "users_active_month", coerce_int(users, "activeMonth"))
        update_numeric(record, "statuses", coerce_int(usage, "localPosts"))

        # ✅ NodeInfo 안에 있는 언어 필드를 싹 긁어서 붙이기
        ni_langs = extract_languages_from_nodeinfo(nodeinfo)
        append_languages(languages, languages_seen, ni_langs)

        # peers
        peers.update(extract_peer_hosts_from_nodeinfo(nodeinfo))
    elif nodeinfo:
        errors.append("nodeinfo: invalid format")

    # ── 여기서 base_url을 결정: NodeInfo가 가리킨 캐노니컬 우선 ──
    base_url = canonical_base or instance.url

    # 캐노니컬 호스트로 레코드 host 업데이트 (같은 존일 때만)
    try:
        if canonical_base:
            canon_host = _normalize_host(urlparse(canonical_base).hostname or "")
            if canon_host and _same_zone(canon_host, _normalize_host(instance.host)):
                if canon_host != _normalize_host(instance.host):
                    record["redirected_from"] = instance.host
                    register_alias(instance.host, canon_host)
                record["host"] = canon_host
    except Exception:
        pass

    platform_data: Optional[Dict[str, Any]] = None

    # 플랫폼 자동 추론 (unknown -> software.name)
    platform = instance.platform
    if platform == "unknown" and record.get("software", {}).get("name"):
        detected_name = record["software"]["name"].lower()
        if "mastodon" in detected_name or "hometown" in detected_name or "glitch" in detected_name:
            platform = "mastodon"
        elif "misskey" in detected_name or "calckey" in detected_name or "firefish" in detected_name:
            platform = "misskey"

    if platform == "mastodon":
        try:
            platform_data = fetch_mastodon(base_url)   # ← 캐노니컬 base 사용
        except FetchError as exc:
            errors.append(f"mastodon: {exc}")
        else:
            record["verified_activitypub"] = True
    elif platform == "misskey":
        try:
            platform_data = fetch_misskey(base_url)    # ← 캐노니컬 base 사용
        except FetchError as exc:
            errors.append(f"misskey: {exc}")
        else:
            record["verified_activitypub"] = True
    elif platform != "unknown":
        pass  # 알 수 없는 플랫폼은 스킵

    if platform_data:
        update_software(record, platform_data.get("software", {}))
        update_open_registrations(record, platform_data.get("open_registrations"))
        update_numeric(record, "users_total", platform_data.get("users_total"))
        update_numeric(record, "users_active_month", platform_data.get("users_active_month"))
        update_numeric(record, "statuses", platform_data.get("statuses"))
        append_languages(languages, languages_seen, platform_data.get("languages"))
        peers.update(normalize_peer_list(platform_data.get("peers")))
    
        # --- 설명 텍스트 저장 (언어 감지 없이) ---
    desc = record.get("nodeinfo_description")
    if not desc and nodeinfo:
        desc = extract_description_from_nodeinfo(nodeinfo)
        if desc:
            record["nodeinfo_description"] = desc
    
    # NodeInfo에서 설명을 가져오지 못했을 때 사이트 메타데이터에서 시도
    if not desc:
        # NodeInfo에서 Content-Type 관련 에러가 난 경우,
        # 사이트 자체가 뭔가 이상한 경우일 가능성이 크니까 HTML 메타데이터는 스킵.
        if any("unexpected Content-Type" in e for e in errors):
            site_details = None
        else:
            site_details = fetch_instance_details(base_url, record["host"])

        if site_details and site_details.get("description"):
            desc = site_details["description"]
            record["nodeinfo_description"] = desc

            site_langs = site_details.get("languages", [])
            append_languages(languages, languages_seen, site_langs)

    
    if desc:
        logging.info("detecting languages from description for host %s", instance.host)
        # 1) 스크립트(문자 범위) 기반으로 ko/ja/en 강제 포함
        script_langs = list(detect_scripts(desc))
        append_languages(languages, languages_seen, script_langs)
        
        # 2) langdetect 결과도 참고 (있으면 추가)
        guessed_langs = detect_languages_from_text(desc)
        append_languages(languages, languages_seen, guessed_langs)

    # 최종 언어 리스트 저장
    record["languages_detected"] = languages
    return record, errors, peers

def extract_metadata_from_html(html: str, host: str) -> Dict[str, Any]:
    try:
        import re
        from html.parser import HTMLParser
    
        result = {
            "description": None,
            "languages": []
        }
    
        # 간단한 정규식으로 메타 태그 추출 (의존성 없이)
        description_patterns = [
            r'<meta\s+name="description"\s+content="([^"]*)"',
            r'<meta\s+property="og:description"\s+content="([^"]*)"',
            r'<meta\s+name="twitter:description"\s+content="([^"]*)"',
            r'<meta\s+property="twitter:description"\s+content="([^"]*)"'
        ]
    
        # 설명 추출
        for pattern in description_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                description = match.group(1).strip()
                if description and len(description) > 10:  # 너무 짧은 설명은 무시
                    result["description"] = description
                    break
    
    # 언어 추출 시도
        lang_match = re.search(r'<html[^>]*\slang="([^"]*)"', html, re.IGNORECASE)
        if not lang_match:
            lang_match = re.search(r'<html[^>]*\sxml:lang="([^"]*)"', html, re.IGNORECASE)
    
        if lang_match:
            lang_code = lang_match.group(1).strip()
            if lang_code:
                normalized = normalize_language_code(lang_code)
                if normalized:
                    result["languages"].append(normalized)
    
        return result
    
    except Exception as e:
        logging.warning("failed to parse HTML metadata for %s: %r", host, e)
        return {"description": None, "languages": []}

def fetch_site_metadata(base_url: str, host: str, include_description: bool = True) -> Optional[Dict[str, Any]]:
    """
    사이트 메타데이터에서 설명과 언어 정보 추출
    """
    if not include_description:
        return None

    if not base_url.startswith(('http://', 'https://')):
        base_url = f"https://{host}"

    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        
        # requests 사용 시
        if requests is not None:
            import requests as _req
            try:
                resp = _req.get(base_url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
                if resp.status_code != 200:
                    return None
                
                content_type = resp.headers.get('content-type', '')
                if 'text/html' not in content_type:
                    return None
                
                return extract_metadata_from_html(resp.text, host)
            except _req.exceptions.RequestException:
                return None
        
        # urllib 사용 시
        else:
            import urllib.request
            request = urllib.request.Request(base_url, headers=headers)
            with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                
                content_type = resp.headers.get('content-type', '')
                if 'text/html' not in content_type:
                    return None
                
                html = resp.read().decode('utf-8', errors='ignore')
                return extract_metadata_from_html(html, host)
                
    except Exception:
        return None

    return None

def fetch_instance_details(base_url: str, host: str) -> Optional[Dict[str, Any]]:
    """
    NodeInfo에서 설명을 가져오지 못했을 때 사이트 메타데이터에서 설명 추출
    """
    # NodeInfo에서 이미 시도했으므로 바로 사이트 메타데이터로 이동
    site_metadata = fetch_site_metadata(base_url, host, include_description=True)
    
    if site_metadata and site_metadata.get("description"):
        return {
            "description": site_metadata["description"],
            "languages": site_metadata.get("languages", [])
        }
    
    return None

def extract_peer_hosts_from_nodeinfo(document: Any) -> Set[str]:
    hosts: Set[str] = set()
    if not isinstance(document, dict):
        return hosts
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        if "peers" in metadata:
            hosts.update(normalize_peer_list(metadata.get("peers")))
        federation = metadata.get("federation")
        if isinstance(federation, dict):
            if "peers" in federation:
                hosts.update(normalize_peer_list(federation.get("peers")))
            if "domains" in federation:
                hosts.update(normalize_peer_list(federation.get("domains")))
    return hosts

def fetch_nodeinfo(host: str) -> Tuple[Dict[str, Any], str]:
    expected = _normalize_host(host)
    last_error: Optional[FetchError] = None
    for scheme in ("https", "http"):
        index_url = f"{scheme}://{expected}/.well-known/nodeinfo"
        try:
            index_payload = request_json(index_url, expected_host=expected)
            if not isinstance(index_payload, dict):
                raise FetchError("unexpected nodeinfo index payload")
            links = index_payload.get("links")
            if not isinstance(links, Sequence):
                raise FetchError("nodeinfo index missing links")
            best_link = select_latest_nodeinfo_link(links)
            if not best_link:
                raise FetchError("no valid nodeinfo links")
            href = best_link.get("href")
            if not isinstance(href, str) or not href:
                raise FetchError("nodeinfo link missing href")

            # 같은 존 허용 + 의심 경로 차단
            _assert_safe_url_relaxed(href, expected)

            # 이 href가 가리키는 호스트/스킴을 '캐노니컬'로 사용
            parsed = urlparse(href)
            canon_host = _normalize_host(parsed.hostname or expected)
            canon_scheme = parsed.scheme or "https"
            canon_base = f"{canon_scheme}://{canon_host}"

            payload = request_json(href, expected_host=expected)
            if not isinstance(payload, dict):
                raise FetchError("unexpected nodeinfo document")
            return payload, canon_base
        except FetchError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise FetchError(str(last_error))
    raise FetchError("nodeinfo endpoint unreachable")

def select_latest_nodeinfo_link(links: Sequence[Any]) -> Optional[Dict[str, Any]]:
    def version_key(link: Dict[str, Any]) -> Tuple[int, int]:
        version = ""
        if isinstance(link, dict):
            rel = link.get("rel")
            href = link.get("href")
            if isinstance(rel, str):
                version = rel.rsplit("/", 1)[-1]
            elif isinstance(href, str):
                version = href.rstrip("/").rsplit("/", 1)[-1]
        major, minor = 0, 0
        if version:
            parts = version.replace("nodeinfo", "").strip("/ ")
            try:
                major_minor = parts.split(".")
                if len(major_minor) >= 2:
                    major = int(major_minor[0])
                    minor = int(major_minor[1])
            except (TypeError, ValueError):
                major, minor = 0, 0
        return major, minor

    candidates = [link for link in links if isinstance(link, dict)]
    if not candidates:
        return None
    return max(candidates, key=version_key)


def fetch_mastodon(base_url: str) -> Dict[str, Any]:
    errors: List[str] = []
    for path in ("/api/v2/instance", "/api/v1/instance"):
        try:
            host = urlparse(base_url).hostname or ""
            payload = request_json(f"{base_url}{path}", expected_host=host)
        except FetchError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(payload, dict):
            continue
        result = parse_mastodon_payload(payload, path.endswith("v2/instance"))
        result["peers"] = sorted(fetch_mastodon_peers(base_url))
        return result
    raise FetchError("; ".join(errors) if errors else "instance API unavailable")


def fetch_mastodon_peers(base_url: str) -> Set[str]:
    try:
        host = urlparse(base_url).hostname or ""
        payload = request_json(f"{base_url}/api/v1/instance/peers", expected_host=host)
    except FetchError:
        return set()
    return normalize_peer_list(payload)


def parse_mastodon_payload(payload: Dict[str, Any], is_v2: bool) -> Dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    users = usage.get("users") if isinstance(usage, dict) else None
    stats = payload.get("stats") if isinstance(payload, dict) else None
    configuration = payload.get("configuration") if isinstance(payload, dict) else None

    result: Dict[str, Any] = {
        "software": {
            "name": payload.get("software", {}).get("name")
            if isinstance(payload.get("software"), dict)
            else payload.get("version") and "mastodon",
            "version": payload.get("version"),
        },
        "open_registrations": payload.get("registrations", {}).get("enabled")
        if isinstance(payload.get("registrations"), dict)
        else payload.get("registrations"),
        "users_total": first_int(
            coerce_int(users, "total"),
            coerce_int(stats, "user_count"),
        ),
        "users_active_month": first_int(
            coerce_int(users, "activeMonth"),
            coerce_int(stats, "active_month"),
        ),
        "statuses": first_int(
            coerce_int(usage, "localPosts"),
            coerce_int(stats, "status_count"),
        ),
        "languages": [],
    }

    lang_seen: set = set()
    if configuration and isinstance(configuration, dict):
        append_languages(result["languages"], lang_seen, configuration.get("languages"))
    elif is_v2:
        append_languages(result["languages"], lang_seen, payload.get("languages"))

    software = payload.get("software")
    if isinstance(software, dict):
        result["software"] = {
            "name": software.get("name"),
            "version": software.get("version"),
        }

    return result


def fetch_misskey(base_url: str) -> Dict[str, Any]:
    host = urlparse(base_url).hostname or ""
    payload = request_json(f"{base_url}/api/meta", method="POST", json_body={"detail": True}, expected_host=host)
    if not isinstance(payload, dict):
        raise FetchError("unexpected meta payload")

    stats = payload.get("stats") if isinstance(payload, dict) else None

    result: Dict[str, Any] = {
        "software": {
            "name": payload.get("softwareName") or "misskey",
            "version": payload.get("version"),
        },
        "open_registrations": payload.get("disableRegistration") is False,
        "users_total": first_int(
            coerce_int(stats, "originalUsersCount"),
            coerce_int(stats, "usersCount"),
        ),
        "users_active_month": first_int(
            coerce_int(stats, "monthlyActiveUsers"),
            coerce_int(stats, "activeUsers"),
        ),
        "statuses": first_int(
            coerce_int(stats, "originalNotesCount"),
            coerce_int(stats, "notesCount"),
        ),
        "languages": [],
    }

    federation = payload.get("federation") if isinstance(payload, dict) else None
    if isinstance(federation, dict):
        result["peers"] = sorted(normalize_peer_list(federation.get("peers")))
    return result


# -------------------------------
# Utilities
# -------------------------------

def emit_peer_suggestions(hosts: Sequence[str], target: str) -> None:
    """
    Save newly discovered peers, excluding ones already checked (ok/bad/legacy).
    """
    if not hosts:
        logging.info("No federation peers discovered.")
        return

    checked_hosts = load_checked_hosts()
    new_hosts = [h for h in hosts if h not in checked_hosts]

    if not new_hosts:
        logging.info("All discovered peers already checked.")
        return

    if target == "-":
        json.dump(new_hosts, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        logging.info("Emitted %d peers to stdout.", len(new_hosts))
        return

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new_hosts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logging.info("Wrote %s (%d new peers).", format_relative(path), len(new_hosts))


def format_relative(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def extract_host(entry: Dict[str, Any]) -> str:
    host = str(entry.get("host", "")).strip().lower()
    if host:
        return _normalize_host(host)

    url = entry.get("url")
    if isinstance(url, str) and url:
        parsed = urlparse(url)
        if parsed.hostname:
            return _normalize_host(parsed.hostname)
        return _normalize_host(url.strip().rstrip("/"))
    return ""


def normalize_base_url(url: str, host: str) -> str:
    if not url:
        return f"https://{host}"
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or host
    path = parsed.path.rstrip("/")
    if not path:
        path = ""
    rebuilt = f"{scheme}://{netloc}{path}"
    return rebuilt.rstrip("/")


def update_software(record: Dict[str, Any], software: Any) -> None:
    if not isinstance(software, dict):
        return
    target = record.get("software")
    if not isinstance(target, dict):
        target = {}
        record["software"] = target
    name = software.get("name")
    version = software.get("version")
    if name and not target.get("name"):
        target["name"] = str(name)
    if version and not target.get("version"):
        target["version"] = str(version)


def update_open_registrations(record: Dict[str, Any], value: Any) -> None:
    boolean = coerce_bool(value)
    if boolean is None:
        return
    if record.get("open_registrations") is None:
        record["open_registrations"] = boolean


def update_numeric(record: Dict[str, Any], key: str, value: Any) -> None:
    number = coerce_int_value(value)
    if number is None:
        return
    if record.get(key) is None:
        record[key] = number

def extract_description_from_nodeinfo(nodeinfo: Dict[str, Any]) -> Optional[str]:
    """
    NodeInfo + metadata에서 서버 설명으로 쓸만한 문자열 하나 뽑기.
    render.js 쪽 로직이랑 비슷하게 우선순위로 고른다.
    """
    if not isinstance(nodeinfo, dict):
        return None

    metadata = nodeinfo.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    candidates = [
        metadata.get("nodeDescription"),
        metadata.get("description"),
        metadata.get("shortDescription"),
        metadata.get("summary"),
        metadata.get("defaultDescription"),
    ]

    node = metadata.get("node")
    if isinstance(node, dict):
        candidates.append(node.get("description"))

    for cand in candidates:
        if cand is None:
            continue
        text = str(cand).strip()
        if text:
            return text
    return None


def extract_languages_from_nodeinfo(nodeinfo: Dict[str, Any]) -> List[str]:
    """
    NodeInfo 안의 여러 언어 필드에서 언어 코드들을 수집해서 리턴.
    usage.languages 외에 metadata.languages 등도 같이 본다.
    """
    if not isinstance(nodeinfo, dict):
        return []

    metadata = nodeinfo.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    usage = nodeinfo.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    collections = [
        metadata.get("languages"),
        metadata.get("language"),
        metadata.get("languages_detected"),
        metadata.get("languagesDetected"),
        isinstance(metadata.get("node"), dict) and metadata["node"].get("languages"),
        usage.get("languages"),
        nodeinfo.get("language"),
    ]

    langs: List[str] = []
    seen = set()

    for values in collections:
        if not values:
            continue
        # append_languages는 dict/list/str 다 받아주니까 그대로 넘겨도 됨
        append_languages(langs, seen, values)

    return langs

def detect_scripts(text: str) -> set[str]:
    langs = set()

    # 한글 (가~힣)
    if any("\uac00" <= ch <= "\ud7a3" for ch in text):
        langs.add("ko")

    # 일본어: 히라가나, 가타카나, 한자 (중국어와 공유하지만, 섞여 있으면 ja로 치는 정도)
    if any(
        ("\u3040" <= ch <= "\u309f") or  # 히라가나
        ("\u30a0" <= ch <= "\u30ff") or  # 가타카나
        ("\u4e00" <= ch <= "\u9fff")     # CJK 통합 한자
        for ch in text
    ):
        langs.add("ja")

    # 라틴 알파벳
    if any(("A" <= ch <= "Z") or ("a" <= ch <= "z") for ch in text):
        langs.add("en")

    return langs

def detect_languages_from_text(text: str,
                               max_langs: int = 5,
                               min_prob: float = 0.2) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    # 입력이 과도하게 긴 경우 잘라버리기 (예: 1000자)
    if len(text) > 1000:
        text = text[:1000]

    try:
        candidates = detect_langs(text)
    except LangDetectException:
        return []
    except Exception as e:
        # 여기에 로그를 잠깐 넣어두면 어느 서버에서 터지는지 바로 알 수 있음
        logging.warning("langdetect failed with unexpected error: %r", e)
        return []

    langs: List[str] = []
    for cand in candidates:
        if cand.prob < min_prob:
            continue
        code = normalize_language_code(cand.lang)
        if code and code not in langs:
            langs.append(code)
        if len(langs) >= max_langs:
            break

    return langs

def append_languages(target: List[str], seen: set, values: Any) -> None:
    if isinstance(values, dict):
        values = values.values()
    if isinstance(values, (str, bytes)):
        values = [values]
    if not isinstance(values, Sequence) and not isinstance(values, set):
        return
    for value in values:
        code = normalize_language_code(value)
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        target.append(code)


def normalize_peer_list(values: Any) -> Set[str]:
    hosts: Set[str] = set()
    if values is None:
        return hosts
    if isinstance(values, dict):
        for item in values.values():
            hosts.update(normalize_peer_list(item))
        return hosts
    if isinstance(values, (list, tuple, set)):
        for item in values:
            hosts.update(normalize_peer_list(item))
        return hosts
    host = normalize_peer_host(values)
    if host:
        hosts.add(host)
    return hosts


def normalize_peer_host(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.rstrip("/")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if parsed.hostname:
            host = parsed.hostname.lower()
            if parsed.port:
                return f"{host}:{parsed.port}"
            return host
        text = text.split("://", 1)[-1]
    return text.lower()


def normalize_language_code(value) -> Optional[str]:
    """
    다양한 표기("en-gb", "korean-KO", "EN_us", "日本語")를
    최대한 간단한 ISO 639-1 코드("en", "ko", "ja", "zh" 등)로 정규화.
    못 알아먹겠으면 None 리턴해서 버린다.
    """
    if value is None:
        return None

    # 리스트, 튜플이 들어오면 대충 첫 번째만 쓴다 (보통 안 들어오게 설계하는 게 좋고)
    if isinstance(value, (list, tuple, set)):
        if not value:
            return None
        value = next(iter(value))

    s = str(value).strip()
    if not s:
        return None

    # 언더스코어 → 하이픈
    s = s.replace("_", "-")
    s_lower = s.lower()

    # 1) 직접 매핑 테이블에 있으면 바로 반환
    if s_lower in LANG_CANON:
        return LANG_CANON[s_lower]

    # 2) "korean-KO" 같은 형태를 name/region 으로 나눠서 다시 시도
    #    (영문/한글/일본어 등 단어 + 지역 코드 섞인 경우)
    parts = re.split(r"[^0-9a-z\uac00-\ud7a3\u3040-\u30ff\u4e00-\u9fff]+", s_lower)
    parts = [p for p in parts if p]
    if len(parts) == 2:
        candidate = f"{parts[0]}-{parts[1]}"
        if candidate in LANG_CANON:
            return LANG_CANON[candidate]
        if parts[0] in LANG_CANON:
            return LANG_CANON[parts[0]]

    # 3) 순수 이름(english, korean, 日本語 등)만 들어온 경우
    if s_lower in LANG_CANON:
        return LANG_CANON[s_lower]

    # 4) 지역 태그 달린 ISO 코드(en-gb, fr-ca 등) → 기본 두 글자로 통일
    if re.fullmatch(r"[a-z]{2}-[a-z0-9]{2,3}", s_lower):
        base = s_lower.split("-", 1)[0]
        if base in LANG_CANON:
            return LANG_CANON[base]
        return base  # 그래도 2글자면 그냥 그걸 쓴다

    # 5) 깔끔한 두 글자 코드면 그대로
    if re.fullmatch(r"[a-z]{2}", s_lower):
        return s_lower

    # 6) 나머지는 버림
    return None


def first_int(*values: Any) -> Optional[int]:
    for value in values:
        number = coerce_int_value(value)
        if number is not None:
            return number
    return None


def coerce_int(mapping: Any, key: str) -> Optional[int]:
    if isinstance(mapping, dict):
        return coerce_int_value(mapping.get(key))
    return None


def coerce_int_value(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value in {"true", "True", "1", 1}:
        return True
    if value in {"false", "False", "0", 0}:
        return False
    return None


def request_json(
    url: str,
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
    expected_host: Optional[str] = None,
) -> Any:
    """
    안전한 JSON 페치:
      - Content-Type 검증 (application/*json)
      - 최대 바이트 제한 (MAX_JSON_BYTES)
      - 동일 호스트 리다이렉트만 허용, MAX_REDIRECTS 제한
      - 바이너리 의심 경로 차단
      - 4xx/5xx 상태코드는 FetchError로 변환
    """
    headers = {
        "Accept": "application/json, */*+json; q=0.9",
        "User-Agent": USER_AGENT,
    }

    if expected_host:
        _assert_safe_url_relaxed(url, expected_host)

    if requests is not None:
    # ----- requests 버전 -----
        import requests as _req
        session = _req.Session()
        session.max_redirects = MAX_REDIRECTS

        class _SameHostAdapter(_req.adapters.HTTPAdapter):
            def build_response(self, req, resp):
                r = super().build_response(req, resp)
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if loc:
                        next_url = urljoin(r.url, loc)
                        if expected_host:
                            _assert_safe_url_relaxed(next_url, expected_host)
                return r

        adapter = _SameHostAdapter(max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        def _do(method: str, url: str, data: Optional[Dict[str, Any]]):
            try:
                resp = session.request(
                    method,
                    url,
                    json=data,
                    timeout=TIMEOUT,
                    headers=headers,
                    stream=True,        # 스트리밍
                    allow_redirects=True,
                )
            except _req.exceptions.RequestException as e:
                # ✅ DNS 실패/연결 실패/타임아웃 등 모든 네트워크 예외를 FetchError로 변환
                raise FetchError(str(e))
                # 🔐 상태코드 직접 검사 (HTTPError로 터지지 않게)
            status = getattr(resp, "status_code", None)
            if status is None or status >= 400:
                raise FetchError(f"HTTP {status or 'unknown'} from {url}")
                # Content-Type 확인
            ct = (resp.headers.get("Content-Type") or "")
            if not _is_json_ct(ct):
                raise FetchError(f"unexpected Content-Type: {ct or 'unknown'}")

            # Content-Length 선검사
            clen = resp.headers.get("Content-Length")
            if clen is not None:
                try:
                    if int(clen) > MAX_JSON_BYTES:
                        raise FetchError(f"payload too large: {clen} bytes")
                except ValueError:
                    pass

                # 본문 제한 읽기
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    buf.extend(chunk)
                    if len(buf) > MAX_JSON_BYTES:
                        raise FetchError(f"payload exceeded {MAX_JSON_BYTES} bytes limit")
            enc = _sanitize_charset(getattr(resp, "encoding", None))
            text = buf.decode(enc, errors="replace")

            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise FetchError(f"Invalid JSON response from {url}: {exc}")

        return _do(method, url, json_body)

    # ----- urllib 버전 -----
    import urllib.error
    import urllib.request

    data_bytes: Optional[bytes] = None
    req_headers = headers.copy()
    if json_body is not None:
        req_headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(json_body).encode("utf-8")

    # 수동 리다이렉트 처리(동일 호스트만)
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        if expected_host:
            _assert_safe_url_relaxed(current_url, expected_host)

        request = urllib.request.Request(current_url, data=data_bytes, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
                # 리다이렉트 처리
                if 300 <= resp.status < 400:
                    loc = resp.headers.get("Location")
                    if not loc:
                        raise FetchError(f"redirect without location from {current_url}")
                    next_url = urljoin(current_url, loc)
                    if expected_host:
                        _assert_safe_url_relaxed(next_url, expected_host)
                    current_url = next_url
                    # 다음 루프로 (리다이렉트 hop)
                    continue

                # 🔐 상태코드 검사
                if resp.status >= 400:
                    raise FetchError(f"HTTP {resp.status} from {current_url}")

                # Content-Type 검사
                ct = resp.headers.get("Content-Type") or ""
                if not _is_json_ct(ct):
                    raise FetchError(f"unexpected Content-Type: {ct or 'unknown'}")

                # Content-Length 선검사
                clen = resp.headers.get("Content-Length")
                if clen is not None:
                    try:
                        if int(clen) > MAX_JSON_BYTES:
                            raise FetchError(f"payload too large: {clen} bytes")
                    except ValueError:
                        pass

                # 제한 읽기
                buf = bytearray()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    if len(buf) > MAX_JSON_BYTES:
                        raise FetchError(f"payload exceeded {MAX_JSON_BYTES} bytes limit")
                enc = _sanitize_charset(resp.headers.get_content_charset())
                text = buf.decode(enc, errors="replace")

        except urllib.error.URLError as exc:
            raise FetchError(str(exc))

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchError(f"Invalid JSON response from {current_url}: {exc}")

    raise FetchError("too many redirects")


if __name__ == "__main__":
    main()
