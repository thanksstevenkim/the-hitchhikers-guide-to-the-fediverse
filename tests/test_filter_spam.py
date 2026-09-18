import pytest

from scripts.filter_spam import check_domain_pattern, is_spam_server


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
        {"host": "mastodon.ml"}, blocklist={"mastodon.ml"}
    ) == (True, "외부 블랙리스트에 등재됨")


def test_existing_domain_keyword_heuristic_still_applies():
    assert check_domain_pattern("casino.example") == (
        True,
        "의심스러운 키워드: casino",
    )
