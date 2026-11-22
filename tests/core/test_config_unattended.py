"""Config keys for unattended scheduled runs (F-024 AC-002, AC-004)."""

from __future__ import annotations

from typing import get_args, get_origin

import pytest

from openjarvis.core.config import (
    DigestConfig,
    SchedulerConfig,
    load_config,
    validate_config_key,
)


class TestSchedulerAllowlists:
    @pytest.mark.parametrize(
        "key", ["scheduler.allowed_agents", "scheduler.allowed_tools"]
    )
    def test_allowlists_are_settable_string_lists(self, key):
        field_type = validate_config_key(key)

        assert get_origin(field_type) is list
        assert get_args(field_type) == (str,)

    def test_allowlists_default_empty(self):
        cfg = SchedulerConfig()

        assert cfg.allowed_agents == []
        assert cfg.allowed_tools == []

    def test_allowlists_default_lists_are_not_shared(self):
        first, second = SchedulerConfig(), SchedulerConfig()
        first.allowed_agents.append("simple")

        assert second.allowed_agents == []

    def test_allowlists_load_from_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text(
            "[scheduler]\n"
            'allowed_agents = ["morning_digest"]\n'
            'allowed_tools = ["digest_collect", "text_to_speech"]\n'
        )

        cfg = load_config(path).scheduler

        assert cfg.allowed_agents == ["morning_digest"]
        assert cfg.allowed_tools == ["digest_collect", "text_to_speech"]


class TestDigestAutoplay:
    def test_autoplay_is_settable_bool(self):
        assert validate_config_key("digest.autoplay") is bool

    def test_autoplay_defaults_false(self):
        assert DigestConfig().autoplay is False

    def test_autoplay_false_when_config_omits_it(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[digest]\npersona = "jarvis"\n')

        assert load_config(path).digest.autoplay is False
