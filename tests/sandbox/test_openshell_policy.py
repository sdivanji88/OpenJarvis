"""Tests for OpenShell policy generation."""

from __future__ import annotations

import json

import pytest

from openjarvis.sandbox.openshell_policy import build_policy, render_policy


class TestDenyAllBase:
    def test_no_hosts_allows_no_network(self):
        policy = build_policy([])
        assert policy["network_policies"] == {}

    def test_runs_as_sandbox_user(self):
        policy = build_policy([])
        assert policy["process"] == {
            "run_as_user": "sandbox",
            "run_as_group": "sandbox",
        }

    def test_only_sandbox_and_tmp_are_writable(self):
        policy = build_policy([])
        assert set(policy["filesystem_policy"]["read_write"]) == {
            "/sandbox",
            "/tmp",
            "/dev/null",
        }


class TestAllowedHosts:
    def test_host_defaults_to_https_port(self):
        policy = build_policy(["example.com"])
        (rule,) = policy["network_policies"].values()
        assert rule["endpoints"] == [{"host": "example.com", "port": 443}]

    def test_explicit_port_is_kept(self):
        policy = build_policy(["feeds.example.com:8443"])
        (rule,) = policy["network_policies"].values()
        assert rule["endpoints"] == [{"host": "feeds.example.com", "port": 8443}]

    def test_all_hosts_share_one_rule(self):
        policy = build_policy(["a.example.com", "b.example.com"])
        (rule,) = policy["network_policies"].values()
        assert [e["host"] for e in rule["endpoints"]] == [
            "a.example.com",
            "b.example.com",
        ]

    def test_rule_allows_the_resolved_sandbox_python(self):
        # OpenShell matches the resolved executable, not the venv symlink.
        policy = build_policy(["example.com"])
        (rule,) = policy["network_policies"].values()
        paths = [b["path"] for b in rule["binaries"]]
        assert "/sandbox/.uv/python/**" in paths

    def test_custom_binaries_replace_the_default(self):
        policy = build_policy(["example.com"], binaries=["/usr/bin/git"])
        (rule,) = policy["network_policies"].values()
        assert rule["binaries"] == [{"path": "/usr/bin/git"}]

    @pytest.mark.parametrize(
        "bad",
        ["https://example.com", "example.com/path", "*.example.com", "", "a b"],
    )
    def test_rejects_anything_but_a_plain_host(self, bad):
        with pytest.raises(ValueError):
            build_policy([bad])

    @pytest.mark.parametrize("bad", ["example.com:0", "example.com:70000"])
    def test_rejects_out_of_range_ports(self, bad):
        with pytest.raises(ValueError):
            build_policy([bad])


class TestRenderPolicy:
    def test_render_is_deterministic(self):
        a = render_policy(build_policy(["b.example.com", "a.example.com"]))
        b = render_policy(build_policy(["b.example.com", "a.example.com"]))
        assert a == b

    def test_render_round_trips_as_json(self):
        policy = build_policy(["example.com"])
        assert json.loads(render_policy(policy)) == policy
