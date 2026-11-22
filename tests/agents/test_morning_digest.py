"""Tests for MorningDigestAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.agents._stubs import AgentResult
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult


def test_morning_digest_registered():
    from openjarvis.agents.morning_digest import MorningDigestAgent

    AgentRegistry.register_value("morning_digest", MorningDigestAgent)
    assert AgentRegistry.contains("morning_digest")


def test_morning_digest_run(tmp_path):
    from openjarvis.agents.morning_digest import MorningDigestAgent

    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": "Good morning sir. AtlasDB 1.0 was released.",
        "finish_reason": "stop",
        "usage": {},
    }

    # Mock collect result
    mock_collect_result = ToolResult(
        tool_name="digest_collect",
        content="=== WORLD ===\n[hackernews] AtlasDB 1.0 Released — 241 points\n",
        success=True,
        metadata={"total_items": 2},
    )

    # Mock TTS result
    mock_tts_result = ToolResult(
        tool_name="text_to_speech",
        content=str(tmp_path / "digest.mp3"),
        success=True,
        metadata={"audio_path": str(tmp_path / "digest.mp3")},
    )

    agent = MorningDigestAgent(
        mock_engine,
        "test-model",
        tools=[],
        persona="jarvis",
        sections=["world"],
        section_sources={"world": ["hackernews", "news_rss"]},
        digest_store_path=str(tmp_path / "digest.db"),
    )

    with patch.object(
        agent._executor,
        "execute",
        side_effect=[mock_collect_result, mock_tts_result],
    ):
        result = agent.run("Generate morning digest")

    assert isinstance(result, AgentResult)
    assert "Good morning" in result.content
    assert result.turns == 1
    assert len(result.tool_results) == 2
    assert set(result.metadata["sources_used"]) == {"hackernews", "news_rss"}
    prompt = "\n".join(
        message.text for message in mock_engine.generate.call_args.args[0]
    ).casefold()
    assert "world —" in prompt
    for forbidden in (
        "messages —|calendar —|health —|rebuttal|dinner at|group chat|"
        "slack|next meeting|readiness|hrv|weather"
    ).split("|"):
        assert forbidden not in prompt


def test_morning_digest_logs_tts_failure(tmp_path, caplog):
    from openjarvis.agents.morning_digest import MorningDigestAgent

    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": "Good morning sir.",
        "finish_reason": "stop",
        "usage": {},
    }
    collect = ToolResult(
        tool_name="digest_collect", content="=== WORLD ===\n", success=True
    )
    tts_failure = ToolResult(
        tool_name="text_to_speech",
        content="TTS error: 400 Model sunsetted",
        success=False,
    )
    agent = MorningDigestAgent(
        mock_engine,
        "test-model",
        tools=[],
        sections=["world"],
        section_sources={"world": ["hackernews"]},
        digest_store_path=str(tmp_path / "digest.db"),
    )

    with patch.object(agent._executor, "execute", side_effect=[collect, tts_failure]):
        with caplog.at_level("WARNING", logger="openjarvis.agents.morning_digest"):
            result = agent.run("Generate morning digest")

    assert result.metadata["audio_path"] == ""
    assert "Model sunsetted" in caplog.text


def test_load_persona():
    from openjarvis.agents.morning_digest import _load_persona

    # Nonexistent persona returns empty string
    result = _load_persona("nonexistent_persona_xyz")
    assert result == ""


def test_persona_lookup_prefers_checkout_then_user_dir(tmp_path, monkeypatch):
    from openjarvis.agents.morning_digest import (
        _load_persona,
        checkout_persona_dir,
        user_persona_dir,
    )

    home = tmp_path / "home"
    monkeypatch.setenv("OPENJARVIS_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    user_dir = user_persona_dir()
    user_dir.mkdir(parents=True)
    (user_dir / "p.md").write_text("from home")

    assert user_dir == home.resolve() / "prompts" / "personas"
    assert _load_persona("p") == "from home"

    checkout = checkout_persona_dir()
    checkout.mkdir(parents=True)
    (checkout / "p.md").write_text("from checkout")

    assert _load_persona("p") == "from checkout"
