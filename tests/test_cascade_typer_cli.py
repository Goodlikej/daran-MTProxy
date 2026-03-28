"""Tests for Cascade Typer CLI subcommands (cascade command group).

Covers: status, list-rules, managed-rules, add-rule, remove-rule,
        reset-rules, apply.

All side effects (discovery, disk writes beyond tmp_path) are mocked.
"""
from __future__ import annotations

import unittest.mock
from pathlib import Path

import pytest
from typer.testing import CliRunner

from daran_proxy_stack.cli.main import app
from daran_proxy_stack.cli.actions.cascade import ActionResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _disc_obj(health="healthy", rules=None, backend="iptables"):
    d = {
        "health": health,
        "installed": True,
        "running": True,
        "confidence": "full",
        "rule_backend": backend,
        "rules": rules or [],
        "warnings": [],
        "errors": [],
    }
    obj = unittest.mock.MagicMock()
    obj.to_dict.return_value = d
    return obj


def _ok_result(**kw) -> ActionResult:
    return ActionResult(ok=True, title="T", body="body", **kw)


def _fail_result(**kw) -> ActionResult:
    return ActionResult(ok=False, title="T", body="body", **kw)


# ---------------------------------------------------------------------------
# cascade status
# ---------------------------------------------------------------------------

class TestCascadeStatusCmd:
    def test_status_ok(self):
        disc = _disc_obj()
        from daran_proxy_stack.modules.cascade import CascadeDiagnostics
        diag = CascadeDiagnostics()
        sdict = {
            "enabled": False, "relay": "127.0.0.1:1080",
            "upstream_socks": "127.0.0.1:40000",
            "relay_reachable": False, "upstream_reachable": False,
            "note": "disabled",
        }
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.collect_diagnostics",
                return_value=diag,
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.cascade.cascade_mod.status_dict",
                    return_value=sdict,
                ):
                    result = runner.invoke(app, ["cascade", "status"])
        assert result.exit_code == 0

    def test_status_shows_output(self):
        disc = _disc_obj(health="healthy")
        from daran_proxy_stack.modules.cascade import CascadeDiagnostics
        diag = CascadeDiagnostics()
        sdict = {
            "enabled": True, "relay": "10.0.0.1:1080",
            "upstream_socks": "10.0.0.2:40000",
            "relay_reachable": True, "upstream_reachable": True,
            "note": "enabled",
        }
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.collect_diagnostics",
                return_value=diag,
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.cascade.cascade_mod.status_dict",
                    return_value=sdict,
                ):
                    result = runner.invoke(app, ["cascade", "status"])
        assert result.exit_code == 0
        assert "10.0.0.1:1080" in result.output


# ---------------------------------------------------------------------------
# cascade list-rules
# ---------------------------------------------------------------------------

class TestCascadeListRulesCmd:
    def test_no_rules(self):
        disc = _disc_obj(rules=[])
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc,
        ):
            result = runner.invoke(app, ["cascade", "list-rules"])
        assert result.exit_code == 0

    def test_with_rules(self):
        rules = [{
            "id": "rule-iptables-001", "protocol": "tcp",
            "listen_port": 443, "target_host": "10.0.0.5",
            "target_port": 8443, "status": "active", "notes": "",
        }]
        disc = _disc_obj(rules=rules)
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc,
        ):
            result = runner.invoke(app, ["cascade", "list-rules"])
        assert result.exit_code == 0
        assert "10.0.0.5" in result.output or ":443" in result.output


# ---------------------------------------------------------------------------
# cascade managed-rules
# ---------------------------------------------------------------------------

class TestCascadeManagedRulesCmd:
    def test_no_rules(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "managed-rules"])
        assert result.exit_code == 0

    def test_with_rules(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=1234, target_host="relay.test", target_port=5678)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "managed-rules"])
        assert result.exit_code == 0
        assert "1234" in result.output
        assert "relay.test" in result.output


# ---------------------------------------------------------------------------
# cascade add-rule
# ---------------------------------------------------------------------------

class TestCascadeAddRuleCmd:
    def test_dry_run_then_abort(self, tmp_path):
        """Without --yes, shows preview, then user aborts."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "add-rule", "tcp", "1080", "127.0.0.1", "40000"],
                input="n\n",
            )
        assert result.exit_code == 0
        assert "1080" in result.output
        from daran_proxy_stack.modules.cascade import load_rules
        assert load_rules(tmp_path) == []

    def test_dry_run_then_confirm(self, tmp_path):
        """Without --yes, shows preview, user confirms → rule written."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "add-rule", "tcp", "1080", "127.0.0.1", "40000"],
                input="y\n",
            )
        assert result.exit_code == 0
        from daran_proxy_stack.modules.cascade import load_rules
        rules = load_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0]["listen_port"] == 1080

    def test_with_yes_flag(self, tmp_path):
        """--yes skips confirmation prompt."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "add-rule", "--yes", "tcp", "2222", "10.0.0.1", "9999"],
            )
        assert result.exit_code == 0
        from daran_proxy_stack.modules.cascade import load_rules
        rules = load_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0]["listen_port"] == 2222

    def test_invalid_protocol_exits_nonzero(self, tmp_path):
        """Invalid protocol returns exit code 1."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "add-rule", "ftp", "80", "host", "80"],
                input="y\n",
            )
        assert result.exit_code != 0

    def test_notes_option(self, tmp_path):
        """--notes flag is stored on the rule."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "add-rule", "--yes", "--notes", "my-relay", "tcp", "3333", "x.y", "4444"],
            )
        assert result.exit_code == 0
        from daran_proxy_stack.modules.cascade import load_rules
        rules = load_rules(tmp_path)
        assert rules[0]["notes"] == "my-relay"


# ---------------------------------------------------------------------------
# cascade remove-rule
# ---------------------------------------------------------------------------

class TestCascadeRemoveRuleCmd:
    def test_not_found_exits_nonzero(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "remove-rule", "nonexistent-id"],
                input="y\n",
            )
        assert result.exit_code != 0

    def test_dry_run_then_abort(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        rule = add_rule(tmp_path, protocol="tcp", listen_port=9999, target_host="h", target_port=1)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "remove-rule", rule["id"]],
                input="n\n",
            )
        assert result.exit_code == 0
        from daran_proxy_stack.modules.cascade import load_rules
        assert len(load_rules(tmp_path)) == 1  # still there

    def test_dry_run_then_confirm(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        rule = add_rule(tmp_path, protocol="tcp", listen_port=9999, target_host="h", target_port=1)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "remove-rule", rule["id"]],
                input="y\n",
            )
        assert result.exit_code == 0
        assert load_rules(tmp_path) == []

    def test_with_yes_flag(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        rule = add_rule(tmp_path, protocol="tcp", listen_port=8888, target_host="z", target_port=2)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(
                app,
                ["cascade", "remove-rule", "--yes", rule["id"]],
            )
        assert result.exit_code == 0
        assert load_rules(tmp_path) == []


# ---------------------------------------------------------------------------
# cascade reset-rules
# ---------------------------------------------------------------------------

class TestCascadeResetRulesCmd:
    def test_no_rules_exits_ok(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "reset-rules"])
        assert result.exit_code == 0

    def test_has_rules_abort(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "reset-rules"], input="n\n")
        assert result.exit_code == 0
        assert len(load_rules(tmp_path)) == 1  # not cleared

    def test_has_rules_confirm(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        add_rule(tmp_path, protocol="udp", listen_port=3, target_host="h", target_port=4)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "reset-rules"], input="y\n")
        assert result.exit_code == 0
        assert load_rules(tmp_path) == []

    def test_with_yes_flag(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "reset-rules", "--yes"])
        assert result.exit_code == 0
        assert load_rules(tmp_path) == []


# ---------------------------------------------------------------------------
# cascade apply
# ---------------------------------------------------------------------------

class TestCascadeApplyCmd:
    def test_dry_run_then_abort(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "apply"], input="n\n")
        assert result.exit_code == 0
        assert not (tmp_path / "cascade" / "3proxy.cfg").exists()

    def test_dry_run_then_confirm(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "apply"], input="y\n")
        assert result.exit_code == 0
        assert (tmp_path / "cascade" / "3proxy.cfg").exists()
        assert (tmp_path / "cascade" / "cascade.service").exists()
        assert (tmp_path / "cascade" / "state.json").exists()

    def test_with_yes_flag(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "apply", "--yes"])
        assert result.exit_code == 0
        assert (tmp_path / "cascade" / "3proxy.cfg").exists()

    def test_apply_with_rules_embeds_portmap(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=7777, target_host="relay.test", target_port=443)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = runner.invoke(app, ["cascade", "apply", "--yes"])
        assert result.exit_code == 0
        cfg_text = (tmp_path / "cascade" / "3proxy.cfg").read_text()
        assert "tcppm" in cfg_text
        assert "-p7777" in cfg_text
        assert "-erelay.test" in cfg_text

    def test_apply_error_exits_nonzero(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.apply",
                side_effect=OSError("disk full"),
            ):
                result = runner.invoke(app, ["cascade", "apply", "--yes"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Cascade group is registered under main app
# ---------------------------------------------------------------------------

class TestCascadeGroupRegistration:
    def test_cascade_in_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "cascade" in result.output

    def test_cascade_subcommands_in_help(self):
        result = runner.invoke(app, ["cascade", "--help"])
        assert result.exit_code == 0
        for cmd in ["status", "list-rules", "managed-rules", "add-rule", "remove-rule", "reset-rules", "apply"]:
            assert cmd in result.output
