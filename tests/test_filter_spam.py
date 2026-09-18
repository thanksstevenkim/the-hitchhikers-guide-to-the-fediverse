import json

import pytest

from scripts.filter_spam import (
    DEFAULT_BLOCKLIST_PATH,
    DomainBlocklist,
    check_blocklist,
    check_domain_pattern,
    filter_spam,
    is_spam_server,
    load_blocklist,
)


@pytest.mark.parametrize(
    "host",
    [
        "mastodon.ml",
        "community.tk",
        "social.ga",
        "friends.cf",
        "notes.gq",
        "fedi.click",
        "social.loan",
        "media.download",
        "club.racing",
        "books.review",
    ],
)
def test_tld_alone_does_not_mark_host_as_spam(host):
    assert check_domain_pattern(host) == (False, None)


def test_confirmed_host_can_still_be_blocked_exactly():
    assert is_spam_server(
        {"host": "mastodon.ml"},
        blocklist=DomainBlocklist(exact_hosts=frozenset({"mastodon.ml"})),
    ) == (True, "차단된 정확한 호스트: mastodon.ml")


@pytest.mark.parametrize(
    "host",
    [
        "activitypub-troll.cf",
        "10ctisdkf.activitypub-troll.cf",
        "nested.example.activitypub-troll.cf",
    ],
)
def test_confirmed_abusive_domain_suffix_blocks_zone(host):
    blocklist = DomainBlocklist(
        domain_suffixes=frozenset({"activitypub-troll.cf"})
    )

    assert check_blocklist(host, blocklist) == (
        True,
        "차단된 도메인 영역: activitypub-troll.cf",
    )


def test_domain_suffix_match_respects_label_boundary():
    blocklist = DomainBlocklist(
        domain_suffixes=frozenset({"activitypub-troll.cf"})
    )

    assert check_blocklist("notactivitypub-troll.cf", blocklist) == (False, None)


def test_structured_blocklist_is_loaded(tmp_path):
    path = tmp_path / "blocklist.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "exact_hosts": ["BLOCKED.EXAMPLE."],
                "domain_suffixes": ["ActivityPub-Troll.CF."],
            }
        ),
        encoding="utf-8",
    )

    assert load_blocklist(str(path)) == DomainBlocklist(
        exact_hosts=frozenset({"blocked.example"}),
        domain_suffixes=frozenset({"activitypub-troll.cf"}),
    )


def test_repository_blocklist_contains_confirmed_abusive_zone():
    blocklist = load_blocklist(str(DEFAULT_BLOCKLIST_PATH))

    assert "activitypub-troll.cf" in blocklist.domain_suffixes


@pytest.mark.parametrize("destination", ["output", "log"])
def test_refilter_does_not_overwrite_its_input(tmp_path, destination):
    input_path = tmp_path / "old-spam-log.json"
    input_path.write_text(
        json.dumps({"filtered_servers": [{"host": "mastodon.ml"}]}),
        encoding="utf-8",
    )
    output_path = (
        input_path if destination == "output" else tmp_path / "recheck.json"
    )
    log_path = (
        input_path if destination == "log" else tmp_path / "new-spam-log.json"
    )

    with pytest.raises(SystemExit) as exc_info:
        filter_spam(
            str(input_path),
            str(output_path),
            str(log_path),
            str(DEFAULT_BLOCKLIST_PATH),
        )

    assert exc_info.value.code == 1
    assert json.loads(input_path.read_text(encoding="utf-8")) == {
        "filtered_servers": [{"host": "mastodon.ml"}]
    }


def test_historical_filter_log_can_be_refiltered(tmp_path):
    input_path = tmp_path / "old-spam-log.json"
    output_path = tmp_path / "recheck.json"
    log_path = tmp_path / "new-spam-log.json"
    blocklist_path = tmp_path / "blocklist.json"
    input_path.write_text(
        json.dumps(
            {
                "filtered_servers": [
                    {
                        "host": "mastodon.ml",
                        "reason": "스팸 TLD: .ml",
                        "platform": None,
                        "stats": {},
                    },
                    {
                        "host": "10ctisdkf.activitypub-troll.cf",
                        "reason": "스팸 TLD: .cf",
                        "platform": None,
                        "stats": {},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    blocklist_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "exact_hosts": [],
                "domain_suffixes": ["activitypub-troll.cf"],
            }
        ),
        encoding="utf-8",
    )

    stats = filter_spam(
        str(input_path),
        str(output_path),
        str(log_path),
        str(blocklist_path),
    )

    assert stats == {
        "total": 2,
        "passed": 1,
        "filtered": 1,
        "filter_rate": 50.0,
    }
    assert json.loads(output_path.read_text(encoding="utf-8")) == [
        {
            "host": "mastodon.ml",
            "reason": "스팸 TLD: .ml",
            "platform": None,
            "stats": {},
        }
    ]
    new_log = json.loads(log_path.read_text(encoding="utf-8"))
    assert new_log["filtered_servers"][0]["host"] == (
        "10ctisdkf.activitypub-troll.cf"
    )
    assert new_log["filtered_servers"][0]["reason"] == (
        "차단된 도메인 영역: activitypub-troll.cf"
    )


def test_existing_domain_keyword_heuristic_still_applies():
    assert check_domain_pattern("casino.example") == (
        True,
        "의심스러운 키워드: casino",
    )
