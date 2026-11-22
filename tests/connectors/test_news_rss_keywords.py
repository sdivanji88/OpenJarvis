"""Tests for the optional topic-keyword filter in NewsRSSConnector."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from openjarvis.connectors.news_rss import NewsRSSConnector


def _rss(*items: tuple[str, str]) -> str:
    """Build an RSS document from ``(title, description)`` pairs."""
    body = "".join(
        f"<item><title>{title}</title><description>{desc}</description>"
        f"<link>https://example.com/{i}</link></item>"
        for i, (title, desc) in enumerate(items)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'


def _connector(tmp_path, keywords=None):
    data = {"feeds": [{"name": "World", "url": "https://example.com/rss.xml"}]}
    if keywords is not None:
        data["keywords"] = keywords
    config_path = tmp_path / "news_rss.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return NewsRSSConnector(config_path=str(config_path))


def _sync_titles(connector, xml_text):
    with patch("openjarvis.connectors.news_rss._fetch_feed", return_value=xml_text):
        return [d.title for d in connector.sync()]


def _configure(connector, feeds, **kwargs):
    with (
        patch("openjarvis.security.ssrf.check_ssrf", return_value=None),
        patch(
            "openjarvis.connectors.news_rss._resolve_host_addresses",
            return_value=("93.184.216.34",),
        ),
    ):
        connector.configure(feeds, **kwargs)


def test_sync_keeps_only_keyword_matches_in_title_or_description(tmp_path):
    connector = _connector(tmp_path, ["startup", "semiconductor"])
    xml_text = _rss(
        ("Election results announced", "Politics as usual."),
        ("Startup raises Series B", "Funding news."),
        ("Weather update", "Rain expected."),
        ("Chip shortage eases", "Semiconductor supply recovers."),
    )

    assert _sync_titles(connector, xml_text) == [
        "Startup raises Series B",
        "Chip shortage eases",
    ]


def test_sync_with_keywords_and_no_matches_yields_nothing(tmp_path):
    connector = _connector(tmp_path, ["semiconductor"])
    xml_text = _rss(("Election results", "Politics."), ("Weather", "Rain."))

    assert _sync_titles(connector, xml_text) == []


def test_sync_keyword_match_is_case_insensitive_and_whole_word(tmp_path):
    connector = _connector(tmp_path, ["AI", "artificial intelligence", "C++"])
    xml_text = _rss(
        ("Crews maintain the bridge", "Said the captain."),
        ("New ai model ships", "Details inside."),
        ("Policy update", "Regulating ARTIFICIAL   Intelligence in 2026."),
        ("Artificial intelligencer is not a word", "Nope."),
        ("New C++ standard lands", "Standards news."),
        ("Ccc++ is not C plus plus", "Nope."),
    )

    assert _sync_titles(connector, xml_text) == [
        "New ai model ships",
        "Policy update",
        "New C++ standard lands",
    ]


def test_sync_caps_keyword_matches_at_five_per_feed_from_wider_window(tmp_path):
    from openjarvis.connectors.news_rss import _MAX_ITEMS_PER_FEED

    connector = _connector(tmp_path, ["tech"])
    filler = [(f"Sports story {i}", "Scores.") for i in range(10)]
    matches = [(f"Tech story {i}", "Gadgets.") for i in range(8)]

    titles = _sync_titles(connector, _rss(*filler, *matches))

    assert _MAX_ITEMS_PER_FEED == 5
    assert titles == [f"Tech story {i}" for i in range(5)]


def test_sync_without_keywords_keeps_first_five_items(tmp_path):
    """A feeds-only config still yields the first five items, unfiltered."""
    connector = _connector(tmp_path)
    xml_text = _rss(*[(f"Story {i}", "Anything.") for i in range(8)])

    assert _sync_titles(connector, xml_text) == [f"Story {i}" for i in range(5)]


def test_sync_ignores_malformed_keyword_entries_on_disk(tmp_path):
    connector = _connector(tmp_path, [42, None, "startup"])
    xml_text = _rss(("Startup news", "x"), ("Other news", "y"))

    assert _sync_titles(connector, xml_text) == ["Startup news"]


def test_sync_ignores_keywords_inside_markup_and_matches_past_truncation(tmp_path):
    connector = _connector(tmp_path, ["AI"])
    xml_text = _rss(
        ("Weather", '&lt;a href="https://x.com/ai/"&gt;link&lt;/a&gt; Rain.'),
        ("Long read", "Filler. " * 40 + "Then an AI twist."),
    )

    with patch("openjarvis.connectors.news_rss._fetch_feed", return_value=xml_text):
        docs = list(connector.sync())

    assert [d.title for d in docs] == ["Long read"]
    assert len(docs[0].content) == 200


def test_configure_without_keywords_keeps_saved_keywords(tmp_path):
    """The connect UI only sends feeds; saving it must not drop the filter."""
    path = tmp_path / "feeds.json"
    connector = NewsRSSConnector(config_path=str(path))
    feeds = [{"url": "https://example.com/feed.xml"}]
    _configure(connector, feeds, keywords=["AI"])

    _configure(connector, feeds)
    assert json.loads(path.read_text(encoding="utf-8"))["keywords"] == ["AI"]

    _configure(connector, feeds, keywords=[])
    assert "keywords" not in json.loads(path.read_text(encoding="utf-8"))


def test_configure_persists_normalized_keywords(tmp_path):
    path = tmp_path / "feeds.json"
    connector = NewsRSSConnector(config_path=str(path))
    _configure(
        connector,
        [{"url": "https://example.com/feed.xml"}],
        keywords=["  AI ", "ai", "", "   ", "Artificial  Intelligence", "Startup"],
    )

    assert json.loads(path.read_text(encoding="utf-8"))["keywords"] == [
        "AI",
        "Artificial Intelligence",
        "Startup",
    ]


def test_configure_without_keywords_omits_the_key(tmp_path):
    path = tmp_path / "feeds.json"
    connector = NewsRSSConnector(config_path=str(path))
    _configure(connector, [{"url": "https://example.com/feed.xml"}])
    assert "keywords" not in json.loads(path.read_text(encoding="utf-8"))

    _configure(connector, [{"url": "https://example.com/feed.xml"}], keywords=["  "])
    assert "keywords" not in json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("keywords", [["AI", 3], "AI", [None]])
def test_configure_rejects_non_string_keywords(tmp_path, keywords):
    path = tmp_path / "feeds.json"
    connector = NewsRSSConnector(config_path=str(path))
    with pytest.raises(ValueError, match="list of strings"):
        _configure(
            connector, [{"url": "https://example.com/feed.xml"}], keywords=keywords
        )
    assert not path.exists()
