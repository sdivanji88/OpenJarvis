"""Tests for news_rss topic keywords on the /v1/connectors connect endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def app():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    from openjarvis.server.connectors_router import create_connectors_router

    _app = FastAPI()
    _app.include_router(create_connectors_router())
    return TestClient(_app)


@pytest.fixture
def news_rss_path(tmp_path: Path):
    """Register a news_rss instance backed by a temp config, with sync stubbed."""
    from openjarvis.connectors.news_rss import NewsRSSConnector
    from openjarvis.server.connectors_router import _instances

    path = tmp_path / "news_rss.json"
    instance = NewsRSSConnector(config_path=str(path))
    instance.sync = lambda **_kwargs: iter(())
    _instances["news_rss"] = instance
    try:
        with (
            patch("openjarvis.security.ssrf.check_ssrf", return_value=None),
            patch(
                "openjarvis.connectors.news_rss._resolve_host_addresses",
                return_value=("93.184.216.34",),
            ),
        ):
            yield path
    finally:
        _instances.pop("news_rss", None)


def _connect(app, keywords):
    return app.post(
        "/v1/connectors/news_rss/connect",
        json={
            "config": {
                "feeds": [{"url": "https://example.com/feed.xml"}],
                "keywords": keywords,
            }
        },
    )


def test_connect_news_rss_passes_keywords_through(app, news_rss_path: Path) -> None:
    resp = _connect(app, [" AI ", "ai", "Startup"])

    assert resp.status_code == 200, resp.text
    assert json.loads(news_rss_path.read_text())["keywords"] == ["AI", "Startup"]


@pytest.mark.parametrize("keywords", ["AI", ["AI", 7], {"a": "b"}])
def test_connect_news_rss_rejects_bad_keywords(
    app, news_rss_path: Path, keywords
) -> None:
    resp = _connect(app, keywords)

    assert resp.status_code == 400
    assert "keywords must be a list of strings" in resp.json()["detail"]
    assert not news_rss_path.exists()
