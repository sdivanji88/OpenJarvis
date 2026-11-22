"""Tests for ``jarvis connect`` CLI command."""

from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli


def test_connect_list_no_connectors() -> None:
    """--list with an empty registry shows a 'no connectors' message."""
    runner = CliRunner()
    with mock.patch(
        "openjarvis.cli.connect_cmd.connect.__wrapped__"
        if hasattr(cli, "__wrapped__")
        else "openjarvis.core.registry.ConnectorRegistry.items",
        return_value=(),
    ):
        with mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.items",
            return_value=(),
        ):
            result = runner.invoke(cli, ["connect", "--list"])

    assert result.exit_code == 0
    assert "No connectors registered" in result.output


def test_connect_list_with_connector(tmp_path: object) -> None:
    """--list with a connector registered shows it in the table."""
    runner = CliRunner()

    # Build a minimal mock connector class
    mock_cls = mock.MagicMock()
    mock_cls.auth_type = "filesystem"
    mock_instance = mock.MagicMock()
    mock_instance.is_connected.return_value = True
    mock_cls.return_value = mock_instance

    with mock.patch(
        "openjarvis.core.registry.ConnectorRegistry.items",
        return_value=(("obsidian", mock_cls),),
    ):
        result = runner.invoke(cli, ["connect", "--list"])

    assert result.exit_code == 0
    assert "obsidian" in result.output


def test_connect_help() -> None:
    """--help exits 0 and mentions the word 'connect'."""
    runner = CliRunner()
    result = runner.invoke(cli, ["connect", "--help"])
    assert result.exit_code == 0
    assert "connect" in result.output.lower()


def test_connect_specific_source(tmp_path: object) -> None:
    """connect --path /nonexistent obsidian shows an error gracefully."""
    runner = CliRunner()

    mock_cls = mock.MagicMock()
    mock_cls.auth_type = "filesystem"
    mock_instance = mock.MagicMock()
    # Path does not exist -> is_connected returns False
    mock_instance.is_connected.return_value = False
    mock_cls.return_value = mock_instance

    with (
        mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.contains",
            return_value=True,
        ),
        mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.get",
            return_value=mock_cls,
        ),
    ):
        # --path before the positional source arg (standard Click group behaviour)
        result = runner.invoke(cli, ["connect", "--path", "/nonexistent", "obsidian"])

    assert result.exit_code == 0
    # Should mention the source and give an indication something went wrong
    assert "obsidian" in result.output or "nonexistent" in result.output


def test_connect_disconnect() -> None:
    """--disconnect gmail exits 0."""
    runner = CliRunner()

    mock_cls = mock.MagicMock()
    mock_instance = mock.MagicMock()
    mock_cls.return_value = mock_instance

    with (
        mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.contains",
            return_value=True,
        ),
        mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.get",
            return_value=mock_cls,
        ),
    ):
        result = runner.invoke(cli, ["connect", "--disconnect", "gmail"])

    assert result.exit_code == 0
    mock_instance.disconnect.assert_called_once()


def _connect_oauth_without_provider(
    hint: str, *, accepts_pasted_token=True, callback_error=None, **invoke_kwargs
):
    """Run ``jarvis connect demo`` for an oauth connector with no provider."""
    mock_cls = mock.MagicMock()
    mock_cls.auth_type = "oauth"
    mock_cls.accepts_pasted_token = accepts_pasted_token
    mock_cls.paste_token_hint = hint
    mock_instance = mock.MagicMock()
    mock_instance.is_connected.return_value = False
    mock_instance.handle_callback.side_effect = callback_error
    mock_cls.return_value = mock_instance

    with (
        mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.contains", return_value=True
        ),
        mock.patch(
            "openjarvis.core.registry.ConnectorRegistry.get", return_value=mock_cls
        ),
        mock.patch(
            "openjarvis.connectors.oauth.get_provider_for_connector",
            return_value=None,
        ),
    ):
        result = CliRunner().invoke(cli, ["connect", "demo"], **invoke_kwargs)
    return result, mock_instance


def test_connect_paste_token_connector_saves_via_handle_callback() -> None:
    result, instance = _connect_oauth_without_provider(
        "Get a token at example.com", input="  secret-token  \n"
    )

    assert result.exit_code == 0
    assert "Get a token at example.com" in result.output
    assert "secret-token" not in result.output
    instance.handle_callback.assert_called_once_with("secret-token")
    assert "demo connected successfully" in result.output


def test_connect_blank_pasted_token_is_not_saved() -> None:
    result, instance = _connect_oauth_without_provider("hint", input="   \n")

    assert result.exit_code == 0
    instance.handle_callback.assert_not_called()
    assert "No token entered" in result.output
    assert "connected successfully" not in result.output


def test_connect_paste_token_reports_rejected_token() -> None:
    result, _ = _connect_oauth_without_provider(
        "hint",
        callback_error=ValueError("token rejected by provider"),
        input="bad\n",
    )

    assert result.exit_code == 0
    assert "token rejected by provider" in result.output
    assert "connected successfully" not in result.output


def test_connect_oauth_without_provider_or_paste_support_points_to_web_ui() -> None:
    result, instance = _connect_oauth_without_provider("", accepts_pasted_token=False)

    assert result.exit_code == 0
    assert "No OAuth provider configured for demo" in result.output
    assert "web UI" in result.output
    instance.handle_callback.assert_not_called()


def test_connect_hint_without_paste_support_does_not_prompt() -> None:
    result, instance = _connect_oauth_without_provider(
        "Get a token at example.com", accepts_pasted_token=False
    )

    assert result.exit_code == 0
    assert "web UI" in result.output
    assert "Get a token at example.com" not in result.output
    assert "Paste your demo token" not in result.output
    instance.handle_callback.assert_not_called()


def test_connect_paste_support_with_empty_hint_still_prompts_and_saves() -> None:
    result, instance = _connect_oauth_without_provider("", input="tok-123\n")

    assert result.exit_code == 0
    assert "Paste your demo token" in result.output
    instance.handle_callback.assert_called_once_with("tok-123")
    assert "demo connected successfully" in result.output


def test_connect_paste_failure_is_not_reported_as_oauth_failure() -> None:
    result, _ = _connect_oauth_without_provider(
        "hint", callback_error=RuntimeError("disk full"), input="tok\n"
    )

    assert "Saving the token failed for demo: disk full" in result.output
    assert "OAuth flow failed" not in result.output


def test_oauth_connectors_do_not_accept_pasted_tokens() -> None:
    from openjarvis.connectors._stubs import BaseConnector
    from openjarvis.connectors.gmail import GmailConnector

    assert BaseConnector.accepts_pasted_token is False
    assert GmailConnector.auth_type == "oauth"
    assert GmailConnector.accepts_pasted_token is False


def test_paste_token_connectors_declare_a_hint_and_have_no_provider() -> None:
    from openjarvis.connectors.granola import GranolaConnector
    from openjarvis.connectors.notion import NotionConnector
    from openjarvis.connectors.oauth import get_provider_for_connector
    from openjarvis.connectors.slack_connector import SlackConnector

    for connector_cls in (NotionConnector, SlackConnector, GranolaConnector):
        assert connector_cls.accepts_pasted_token is True
        assert connector_cls.paste_token_hint
        assert get_provider_for_connector(connector_cls.connector_id) is None
