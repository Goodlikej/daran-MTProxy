"""Tests for cli.actions.cascade and cli.actions.xui.

All shell calls and detection functions are mocked — no actual system changes.
"""
from __future__ import annotations

import unittest.mock
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import pytest

from daran_proxy_stack.cli.actions import cascade as cascade_actions
from daran_proxy_stack.cli.actions import xui as xui_actions


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _make_cascade_discovery_state(health="healthy", rules=None, backend="iptables"):
    """Return a minimal dict that detect_cascade().to_dict() would produce."""
    return {
        "health": health,
        "installed": True,
        "running": True,
        "confidence": "full",
        "rule_backend": backend,
        "rules": rules or [],
        "warnings": [],
        "errors": [],
    }


def _make_cascade_disc_obj(health="healthy", rules=None, backend="iptables"):
    """Return a mock object with to_dict()."""
    d = _make_cascade_discovery_state(health, rules, backend)
    obj = unittest.mock.MagicMock()
    obj.to_dict.return_value = d
    return obj


# ---------------------------------------------------------------------------
# cascade.status()
# ---------------------------------------------------------------------------

class TestCascadeActionsStatus:
    def test_status_returns_result(self):
        disc_obj = _make_cascade_disc_obj(health="healthy")
        from daran_proxy_stack.modules.cascade import CascadeDiagnostics
        diag = CascadeDiagnostics(
            note="enabled — checking connectivity",
            config_present=True,
            relay_reachable=True,
            upstream_reachable=True,
        )
        sdict = {
            "enabled": True,
            "relay": "127.0.0.1:1080",
            "upstream_socks": "127.0.0.1:40000",
            "relay_reachable": True,
            "upstream_reachable": True,
            "note": "enabled — checking connectivity",
        }
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc_obj,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.collect_diagnostics",
                return_value=diag,
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.cascade.cascade_mod.status_dict",
                    return_value=sdict,
                ):
                    result = cascade_actions.status()
        assert isinstance(result, cascade_actions.ActionResult)
        assert "127.0.0.1:1080" in result.body
        assert "iptables" in result.body

    def test_status_with_rules(self):
        rules = [
            {
                "id": "rule-iptables-000",
                "protocol": "tcp",
                "listen_port": 443,
                "target_host": "10.0.0.2",
                "target_port": 8443,
                "status": "active",
                "notes": "observed from iptables",
            }
        ]
        disc_obj = _make_cascade_disc_obj(rules=rules)
        from daran_proxy_stack.modules.cascade import CascadeDiagnostics
        diag = CascadeDiagnostics()
        sdict = {
            "enabled": False,
            "relay": "127.0.0.1:1080",
            "upstream_socks": "127.0.0.1:40000",
            "relay_reachable": False,
            "upstream_reachable": False,
            "note": "disabled in config",
        }
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc_obj,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.collect_diagnostics",
                return_value=diag,
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.cascade.cascade_mod.status_dict",
                    return_value=sdict,
                ):
                    result = cascade_actions.status()
        assert "rule-iptables-000" in result.body
        assert "10.0.0.2:8443" in result.body

    def test_status_discovery_error(self):
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            side_effect=RuntimeError("iptables fail"),
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.collect_diagnostics",
                side_effect=RuntimeError("also fail"),
            ):
                result = cascade_actions.status()
        assert not result.ok
        assert "Ошибка" in result.body


# ---------------------------------------------------------------------------
# cascade.list_rules()
# ---------------------------------------------------------------------------

class TestCascadeActionsListRules:
    def test_no_rules_returns_ok(self):
        disc_obj = _make_cascade_disc_obj(health="stopped", rules=[])
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc_obj,
        ):
            result = cascade_actions.list_rules()
        assert result.ok
        assert "не обнаружены" in result.body.lower() or "не обнаружен" in result.body.lower()

    def test_with_rules(self):
        rules = [
            {
                "id": "rule-iptables-000",
                "protocol": "tcp",
                "listen_port": 1234,
                "target_host": "10.10.10.1",
                "target_port": 5678,
                "status": "active",
                "notes": "",
            }
        ]
        disc_obj = _make_cascade_disc_obj(rules=rules)
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc_obj,
        ):
            result = cascade_actions.list_rules()
        assert result.ok
        assert ":1234" in result.body
        assert "10.10.10.1:5678" in result.body

    def test_detection_error(self):
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            side_effect=RuntimeError("boom"),
        ):
            result = cascade_actions.list_rules()
        assert not result.ok
        assert "boom" in result.body


# ---------------------------------------------------------------------------
# cascade.apply_config()
# ---------------------------------------------------------------------------

class TestCascadeActionsApplyConfig:
    def test_unconfirmed_returns_plan(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=Path("/tmp/fake-artifacts"),
        ):
            result = cascade_actions.apply_config(confirmed=False)
        assert not result.ok
        assert "3proxy.cfg" in result.body
        assert "cascade.service" in result.body

    def test_confirmed_writes_files(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.apply_config(confirmed=True)
        assert result.ok
        assert (tmp_path / "cascade" / "3proxy.cfg").exists()
        assert (tmp_path / "cascade" / "cascade.service").exists()
        assert (tmp_path / "cascade" / "state.json").exists()

    def test_confirmed_fail_handled(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.apply",
                side_effect=OSError("disk full"),
            ):
                result = cascade_actions.apply_config(confirmed=True)
        assert not result.ok
        assert "disk full" in result.body


# ---------------------------------------------------------------------------
# cascade.show_config()
# ---------------------------------------------------------------------------

class TestCascadeActionsShowConfig:
    def test_no_files_returns_not_ok(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.show_config()
        assert not result.ok
        assert "не найдены" in result.body

    def test_with_cfg_file(self, tmp_path):
        cascade_dir = tmp_path / "cascade"
        cascade_dir.mkdir()
        (cascade_dir / "3proxy.cfg").write_text("nscache 65536\n")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.show_config()
        assert result.ok
        assert "3proxy.cfg" in result.body
        assert "nscache 65536" in result.body


# ---------------------------------------------------------------------------
# cascade.install_3proxy_guide()
# ---------------------------------------------------------------------------

class TestCascadeActionsInstall3proxyGuide:
    def test_not_installed(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            result = cascade_actions.install_3proxy_guide()
        assert not result.ok
        assert "apt-get" in result.body or "установка" in result.body.lower()

    def test_already_installed(self):
        from daran_proxy_stack.lib.shell import CommandResult
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/3proxy"):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.run",
                return_value=CommandResult("/usr/bin/3proxy --version", 0, "3proxy 0.9.5", ""),
            ):
                result = cascade_actions.install_3proxy_guide()
        assert result.ok
        assert "установлен" in result.body.lower()


# ---------------------------------------------------------------------------
# xui.status()
# ---------------------------------------------------------------------------

class TestXuiActionsStatus:
    def _patch_all(
        self,
        unit_exists=False,
        is_active=False,
        process_running=False,
        binary=None,
        web_up=False,
    ):
        return unittest.mock.patch.multiple(
            "daran_proxy_stack.cli.actions.xui",
            _detect_xui_systemd=unittest.mock.Mock(return_value=(unit_exists, is_active)),
            _detect_xui_process=unittest.mock.Mock(return_value=process_running),
            _detect_xui_binary=unittest.mock.Mock(return_value=binary),
            _probe_web_ui=unittest.mock.Mock(return_value=web_up),
        )

    def test_not_installed(self):
        with self._patch_all():
            result = xui_actions.status()
        assert not result.ok  # not running
        assert "не обнаружен" in result.body or "не найден" in result.body

    def test_running_with_web(self):
        with self._patch_all(
            unit_exists=True,
            is_active=True,
            binary="/usr/local/x-ui/x-ui",
            web_up=True,
        ):
            result = xui_actions.status()
        assert result.ok
        assert "2053" in result.body

    def test_installed_but_stopped(self):
        with self._patch_all(unit_exists=True, binary="/usr/local/x-ui/x-ui"):
            result = xui_actions.status()
        assert not result.ok  # not running
        assert "systemctl start x-ui" in result.body


# ---------------------------------------------------------------------------
# xui.install_guide()  (legacy guide-only path — still present)
# ---------------------------------------------------------------------------

class TestXuiActionsInstallGuide:
    def _patch_detect(self, binary=None, unit_exists=False):
        return unittest.mock.patch.multiple(
            "daran_proxy_stack.cli.actions.xui",
            _detect_xui_systemd=unittest.mock.Mock(return_value=(unit_exists, False)),
            _detect_xui_binary=unittest.mock.Mock(return_value=binary),
        )

    def test_unconfirmed_shows_plan(self):
        with self._patch_detect():
            result = xui_actions.install_guide(confirmed=False)
        assert not result.ok
        assert "curl" in result.body
        assert "mhsanaei" in result.body

    def test_confirmed_shows_full_instructions(self):
        with self._patch_detect():
            result = xui_actions.install_guide(confirmed=True)
        assert result.ok
        assert "bash <(curl" in result.body
        assert "admin" in result.body

    def test_already_installed_returns_ok(self):
        with self._patch_detect(binary="/usr/local/x-ui/x-ui"):
            result = xui_actions.install_guide(confirmed=False)
        assert result.ok
        assert "уже установлен" in result.body


# ---------------------------------------------------------------------------
# xui.install_xui_pro_upstream()  (upstream backend: mozaroc/x-ui-pro)
# ---------------------------------------------------------------------------

class TestXuiActionsInstallXuiProUpstream:
    """Tests for the temporary upstream-backed installer (mozaroc/x-ui-pro).

    Attribution: vendor/xui-pro/NOTICE.md
    This installer path is temporary — will be replaced by native installer.
    """

    def _patch_detect(self, binary=None, unit_exists=False):
        return unittest.mock.patch.multiple(
            "daran_proxy_stack.cli.actions.xui",
            _detect_xui_systemd=unittest.mock.Mock(return_value=(unit_exists, False)),
            _detect_xui_binary=unittest.mock.Mock(return_value=binary),
        )

    def test_unconfirmed_shows_attribution_and_source_url(self):
        """Preview must show upstream attribution and the exact source URL."""
        with self._patch_detect():
            result = xui_actions.install_xui_pro_upstream(confirmed=False)
        assert not result.ok
        # Must show attribution
        assert "mozaroc" in result.body
        assert "x-ui-pro" in result.body
        # Must show the upstream source URL
        assert "github.com/mozaroc/x-ui-pro" in result.body
        # Must show the install command so operator can inspect it
        assert "wget" in result.body or "x-ui-pro.sh" in result.body
        # Must warn about root
        assert "root" in result.body.lower() or "⚠" in result.body

    def test_unconfirmed_shows_nginx_reality_features(self):
        """Preview should mention what the script installs."""
        with self._patch_detect():
            result = xui_actions.install_xui_pro_upstream(confirmed=False)
        # Should mention nginx / REALITY in feature list
        assert "nginx" in result.body.lower() or "reality" in result.body.lower()

    def test_already_installed_returns_ok(self):
        with self._patch_detect(binary="/usr/local/x-ui/x-ui"):
            result = xui_actions.install_xui_pro_upstream(confirmed=False)
        assert result.ok
        assert "уже установлен" in result.body

    def test_already_installed_unit_only(self):
        with self._patch_detect(unit_exists=True):
            result = xui_actions.install_xui_pro_upstream(confirmed=False)
        assert result.ok
        assert "уже установлен" in result.body

    def test_confirmed_no_wget(self):
        """If wget is not found, return error with manual command hint."""
        with self._patch_detect():
            with unittest.mock.patch("shutil.which", return_value=None):
                result = xui_actions.install_xui_pro_upstream(confirmed=True)
        assert not result.ok
        assert "wget" in result.body.lower()

    def test_confirmed_runs_upstream_script_success(self):
        """confirmed=True with wget present should call run_live() and return ok on success."""
        from daran_proxy_stack.lib.shell import CommandResult
        with self._patch_detect():
            with unittest.mock.patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.xui.run_live",
                    return_value=CommandResult("sudo bash ...", 0, "Installation complete", ""),
                ) as mock_run:
                    result = xui_actions.install_xui_pro_upstream(confirmed=True)
        assert result.ok
        assert "завершён" in result.body or "complete" in result.body
        # The run_live call must reference the upstream script URL
        call_args = mock_run.call_args[0][0]
        assert any("mozaroc" in str(a) or "x-ui-pro" in str(a) for a in call_args)

    def test_confirmed_runs_upstream_script_failure(self):
        """confirmed=True with script failure should return not ok with error detail."""
        from daran_proxy_stack.lib.shell import CommandResult
        with self._patch_detect():
            with unittest.mock.patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.xui.run_live",
                    return_value=CommandResult("sudo bash ...", 1, "", "connection refused"),
                ):
                    result = xui_actions.install_xui_pro_upstream(confirmed=True)
        assert not result.ok
        assert "connection refused" in result.body


# ---------------------------------------------------------------------------
# xui.service_restart()
# ---------------------------------------------------------------------------

class TestXuiActionsServiceRestart:
    def test_no_systemctl(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            result = xui_actions.service_restart()
        assert not result.ok

    def test_unit_not_found(self):
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/systemctl"):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.xui._detect_xui_systemd",
                return_value=(False, False),
            ):
                result = xui_actions.service_restart()
        assert not result.ok
        assert "не найден" in result.body

    def test_restart_ok(self):
        from daran_proxy_stack.lib.shell import CommandResult
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/systemctl"):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.xui._detect_xui_systemd",
                return_value=(True, True),
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.xui.run",
                    return_value=CommandResult("sudo systemctl restart x-ui", 0, "", ""),
                ):
                    result = xui_actions.service_restart()
        assert result.ok
        assert "ok" in result.body.lower()

    def test_restart_fail(self):
        from daran_proxy_stack.lib.shell import CommandResult
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/systemctl"):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.xui._detect_xui_systemd",
                return_value=(True, True),
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.xui.run",
                    return_value=CommandResult("sudo systemctl restart x-ui", 1, "", "failed to restart"),
                ):
                    result = xui_actions.service_restart()
        assert not result.ok
        assert "failed to restart" in result.body


# ---------------------------------------------------------------------------
# Menu integration: Cascade and 3x-ui submenus
# ---------------------------------------------------------------------------

class TestMenuCascadeSubMenuActions:
    """Smoke-test Cascade submenu choices."""

    def _run(self, choices: list[str]):
        inputs = deque(choices)
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            from daran_proxy_stack.cli.menu import run_menu
            run_menu(input_fn=lambda: inputs.popleft())

    def test_cascade_status(self):
        """Choice '1' = system status."""
        disc_obj = _make_cascade_disc_obj()
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
            return_value=disc_obj,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade.cascade_mod.collect_diagnostics",
                return_value=diag,
            ):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.cascade.cascade_mod.status_dict",
                    return_value=sdict,
                ):
                    # 2=Cascade submenu, 1=status, 0=back, 0=exit
                    self._run(["2", "1", "0", "0"])

    def test_cascade_list_rules(self):
        """Choice '2' = list rules."""
        disc_obj = _make_cascade_disc_obj(rules=[])
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.modules.cascade.detect_cascade",
            return_value=disc_obj,
        ):
            self._run(["2", "2", "0", "0"])

    def test_cascade_show_config_no_files(self, tmp_path):
        """Choice '3' = show config, no files."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            self._run(["2", "3", "0", "0"])

    def test_cascade_apply_config_cancel(self, tmp_path):
        """Choice '4' → apply config → cancel."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            self._run(["2", "4", "n", "0", "0"])

    def test_cascade_3proxy_guide_not_installed(self):
        """Choice '5' = 3proxy guide."""
        with unittest.mock.patch("shutil.which", return_value=None):
            self._run(["2", "5", "0", "0"])


class TestMenu3xuiSubMenuActions:
    """Smoke-test 3x-ui submenu choices."""

    def _run(self, choices: list[str]):
        inputs = deque(choices)
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            from daran_proxy_stack.cli.menu import run_menu
            run_menu(input_fn=lambda: inputs.popleft())

    def _patch_xui_detect(self, binary=None, unit_exists=False, is_active=False, process=False, web=False):
        return unittest.mock.patch.multiple(
            "daran_proxy_stack.cli.actions.xui",
            _detect_xui_systemd=unittest.mock.Mock(return_value=(unit_exists, is_active)),
            _detect_xui_process=unittest.mock.Mock(return_value=process),
            _detect_xui_binary=unittest.mock.Mock(return_value=binary),
            _probe_web_ui=unittest.mock.Mock(return_value=web),
        )

    def test_xui_status_not_installed(self):
        """Choice '1' = status, nothing installed."""
        with self._patch_xui_detect():
            self._run(["4", "1", "0", "0"])

    def test_xui_install_cancel(self):
        """Choice '2' → upstream install preview → cancel.

        Uses mozaroc/x-ui-pro upstream backend (temporary external installer).
        Attribution: vendor/xui-pro/NOTICE.md
        """
        with self._patch_xui_detect():
            self._run(["4", "2", "n", "0", "0"])

    def test_xui_install_confirm_runs_upstream(self):
        """Choice '2' → upstream install → confirm → mock successful run.

        Verifies the menu wires to install_xui_pro_upstream (not install_guide).
        """
        from daran_proxy_stack.lib.shell import CommandResult
        with self._patch_xui_detect():
            with unittest.mock.patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                with unittest.mock.patch(
                    "daran_proxy_stack.cli.actions.xui.run",
                    return_value=CommandResult("sudo su ...", 0, "ok", ""),
                ):
                    self._run(["4", "2", "y", "0", "0"])

    def test_xui_restart_no_systemctl(self):
        """Choice '3' = restart, no systemctl."""
        with unittest.mock.patch("shutil.which", return_value=None):
            self._run(["4", "3", "0", "0"])


# ---------------------------------------------------------------------------
# cascade rule management: modules/cascade primitives
# ---------------------------------------------------------------------------

class TestCascadeRuleManagementPrimitives:
    """Unit tests for load_rules / save_rules / add_rule / remove_rule / reset_rules."""

    def test_load_rules_empty_when_no_file(self, tmp_path):
        from daran_proxy_stack.modules.cascade import load_rules
        assert load_rules(tmp_path) == []

    def test_load_rules_malformed_file_returns_empty(self, tmp_path):
        from daran_proxy_stack.modules.cascade import load_rules
        (tmp_path / "cascade").mkdir()
        (tmp_path / "cascade" / "rules.json").write_text("not json", encoding="utf-8")
        assert load_rules(tmp_path) == []

    def test_save_and_load_roundtrip(self, tmp_path):
        from daran_proxy_stack.modules.cascade import save_rules, load_rules
        rules = [{"id": "r1", "protocol": "tcp", "listen_port": 1234, "target_host": "10.0.0.1", "target_port": 5678, "status": "managed", "notes": ""}]
        save_rules(tmp_path, rules)
        loaded = load_rules(tmp_path)
        assert loaded == rules

    def test_add_rule_creates_entry(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        rule = add_rule(tmp_path, protocol="tcp", listen_port=1080, target_host="127.0.0.1", target_port=40000)
        assert rule["protocol"] == "tcp"
        assert rule["listen_port"] == 1080
        assert rule["target_host"] == "127.0.0.1"
        assert rule["target_port"] == 40000
        assert rule["id"].startswith("rule-managed-")
        rules = load_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0]["id"] == rule["id"]

    def test_add_rule_accumulates(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        add_rule(tmp_path, protocol="tcp", listen_port=1080, target_host="a.b", target_port=8080)
        add_rule(tmp_path, protocol="udp", listen_port=1081, target_host="c.d", target_port=9090)
        assert len(load_rules(tmp_path)) == 2

    def test_remove_rule_found(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, remove_rule, load_rules
        rule = add_rule(tmp_path, protocol="tcp", listen_port=1234, target_host="x", target_port=4567)
        removed = remove_rule(tmp_path, rule["id"])
        assert removed is True
        assert load_rules(tmp_path) == []

    def test_remove_rule_not_found(self, tmp_path):
        from daran_proxy_stack.modules.cascade import remove_rule
        removed = remove_rule(tmp_path, "nonexistent-id")
        assert removed is False

    def test_reset_rules_clears_all(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, reset_rules, load_rules
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        add_rule(tmp_path, protocol="tcp", listen_port=3, target_host="h", target_port=4)
        count = reset_rules(tmp_path)
        assert count == 2
        assert load_rules(tmp_path) == []

    def test_reset_rules_empty(self, tmp_path):
        from daran_proxy_stack.modules.cascade import reset_rules
        count = reset_rules(tmp_path)
        assert count == 0


# ---------------------------------------------------------------------------
# cascade.list_managed_rules() action
# ---------------------------------------------------------------------------

class TestCascadeActionsListManagedRules:
    def test_no_rules(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.list_managed_rules()
        assert result.ok
        assert "нет" in result.body.lower()

    def test_with_rules(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=1234, target_host="10.0.0.1", target_port=5678, notes="test rule")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.list_managed_rules()
        assert result.ok
        assert ":1234" in result.body
        assert "10.0.0.1:5678" in result.body
        assert "test rule" in result.body


# ---------------------------------------------------------------------------
# cascade.add_rule() action
# ---------------------------------------------------------------------------

class TestCascadeActionsAddRule:
    def test_unconfirmed_returns_preview(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.add_rule(
                protocol="tcp", listen_port=1080, target_host="127.0.0.1",
                target_port=40000, confirmed=False,
            )
        assert not result.ok
        assert "1080" in result.body
        assert "127.0.0.1" in result.body

    def test_confirmed_writes_rule(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.add_rule(
                protocol="tcp", listen_port=1080, target_host="127.0.0.1",
                target_port=40000, notes="test", confirmed=True,
            )
        assert result.ok
        assert "rule-managed-" in result.body
        # rule should be in file
        from daran_proxy_stack.modules.cascade import load_rules
        rules = load_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0]["listen_port"] == 1080

    def test_invalid_protocol(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.add_rule(
                protocol="ftp", listen_port=80, target_host="x", target_port=80, confirmed=False,
            )
        assert not result.ok
        assert "Неверный протокол" in result.body

    def test_invalid_listen_port(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.add_rule(
                protocol="tcp", listen_port=99999, target_host="x", target_port=80, confirmed=False,
            )
        assert not result.ok
        assert "порт" in result.body.lower()

    def test_empty_target_host(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.add_rule(
                protocol="tcp", listen_port=1080, target_host="", target_port=80, confirmed=False,
            )
        assert not result.ok
        assert "хост" in result.body.lower()


# ---------------------------------------------------------------------------
# cascade.remove_rule() action
# ---------------------------------------------------------------------------

class TestCascadeActionsRemoveRule:
    def test_rule_not_found_returns_not_ok(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.remove_rule("nonexistent-id", confirmed=False)
        assert not result.ok
        assert "не найдено" in result.body

    def test_unconfirmed_shows_preview(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        rule = add_rule(tmp_path, protocol="tcp", listen_port=1234, target_host="x.y", target_port=9)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.remove_rule(rule["id"], confirmed=False)
        assert not result.ok
        assert rule["id"] in result.body
        assert ":1234" in result.body

    def test_confirmed_removes_rule(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        rule = add_rule(tmp_path, protocol="tcp", listen_port=4321, target_host="a.b", target_port=7)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.remove_rule(rule["id"], confirmed=True)
        assert result.ok
        assert rule["id"] in result.body
        assert load_rules(tmp_path) == []


# ---------------------------------------------------------------------------
# cascade.reset_rules() action
# ---------------------------------------------------------------------------

class TestCascadeActionsResetRules:
    def test_no_rules_returns_ok_immediately(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.reset_rules(confirmed=False)
        assert result.ok
        assert "нечего" in result.body

    def test_unconfirmed_shows_destructive_warning(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        add_rule(tmp_path, protocol="tcp", listen_port=3, target_host="h", target_port=4)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.reset_rules(confirmed=False)
        assert not result.ok
        # Should mention count and destructive nature
        assert "2" in result.body
        assert "⚠" in result.body or "необратимо" in result.body

    def test_confirmed_clears_rules(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule, load_rules
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        add_rule(tmp_path, protocol="tcp", listen_port=3, target_host="h", target_port=4)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.reset_rules(confirmed=True)
        assert result.ok
        assert "2" in result.body
        assert load_rules(tmp_path) == []


# ---------------------------------------------------------------------------
# Menu integration: new Cascade rule management submenu choices (6/7/8/9)
# ---------------------------------------------------------------------------

class TestMenuCascadeRuleManagementFlow:
    """Smoke-test new rule management items 6/7/8/9 in Cascade submenu."""

    def _run(self, choices: list[str], tmp_path):
        inputs = deque(choices)
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
                return_value=tmp_path,
            ):
                from daran_proxy_stack.cli.menu import run_menu
                run_menu(input_fn=lambda: inputs.popleft())

    def test_list_managed_rules_empty(self, tmp_path):
        """Choice 6 = list managed rules, no rules."""
        self._run(["2", "6", "0", "0"], tmp_path)

    def test_add_rule_cancel(self, tmp_path):
        """Choice 7 = add rule flow, cancel at confirm."""
        # protocol / listen_port / target_host / target_port / notes / confirm=n
        self._run(["2", "7", "tcp", "1080", "127.0.0.1", "40000", "", "n", "0", "0"], tmp_path)

    def test_add_rule_confirm(self, tmp_path):
        """Choice 7 = add rule flow, confirm."""
        self._run(["2", "7", "tcp", "1080", "127.0.0.1", "40000", "", "y", "0", "0"], tmp_path)
        from daran_proxy_stack.modules.cascade import load_rules
        rules = load_rules(tmp_path)
        assert len(rules) == 1
        assert rules[0]["listen_port"] == 1080

    def test_remove_rule_no_rules(self, tmp_path):
        """Choice 8 = remove rule, no rules — should just show empty list and return."""
        self._run(["2", "8", "0", "0"], tmp_path)

    def test_remove_rule_confirm(self, tmp_path):
        """Choice 8 = remove rule flow, confirm removal."""
        from daran_proxy_stack.modules.cascade import add_rule
        rule = add_rule(tmp_path, protocol="tcp", listen_port=4321, target_host="x", target_port=7)
        # list_managed_rules → enter rule_id → confirm
        self._run(["2", "8", rule["id"], "y", "0", "0"], tmp_path)
        from daran_proxy_stack.modules.cascade import load_rules
        assert load_rules(tmp_path) == []

    def test_reset_rules_cancel(self, tmp_path):
        """Choice 9 = reset rules, cancel."""
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        self._run(["2", "9", "n", "0", "0"], tmp_path)
        # Rules should still exist
        from daran_proxy_stack.modules.cascade import load_rules
        assert len(load_rules(tmp_path)) == 1

    def test_reset_rules_confirm(self, tmp_path):
        """Choice 9 = reset rules, confirm."""
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=1, target_host="h", target_port=2)
        self._run(["2", "9", "y", "0", "0"], tmp_path)
        from daran_proxy_stack.modules.cascade import load_rules
        assert load_rules(tmp_path) == []


# ---------------------------------------------------------------------------
# Integration: managed rules → render_3proxy_config / apply
# ---------------------------------------------------------------------------

class TestCascadeManagedRulesIntegration:
    """Verify that managed rules.json content feeds into generated 3proxy.cfg."""

    # --- render_rules_section ---

    def test_render_rules_section_empty(self):
        from daran_proxy_stack.modules.cascade import render_rules_section
        assert render_rules_section([]) == ""

    def test_render_rules_section_tcp(self):
        from daran_proxy_stack.modules.cascade import render_rules_section
        rules = [{"protocol": "tcp", "listen_port": 1234, "target_host": "10.0.0.1", "target_port": 5678, "notes": ""}]
        out = render_rules_section(rules)
        assert "tcppm" in out
        assert "-p1234" in out
        assert "-e10.0.0.1" in out
        assert "-E5678" in out
        assert "udppm" not in out

    def test_render_rules_section_udp(self):
        from daran_proxy_stack.modules.cascade import render_rules_section
        rules = [{"protocol": "udp", "listen_port": 5000, "target_host": "a.b.c", "target_port": 9000, "notes": ""}]
        out = render_rules_section(rules)
        assert "udppm" in out
        assert "tcppm" not in out

    def test_render_rules_section_both(self):
        from daran_proxy_stack.modules.cascade import render_rules_section
        rules = [{"protocol": "both", "listen_port": 7000, "target_host": "x.y", "target_port": 7001, "notes": ""}]
        out = render_rules_section(rules)
        assert "tcppm" in out
        assert "udppm" in out

    def test_render_rules_section_notes_as_comment(self):
        from daran_proxy_stack.modules.cascade import render_rules_section
        rules = [{"protocol": "tcp", "listen_port": 80, "target_host": "h", "target_port": 8080, "notes": "my relay"}]
        out = render_rules_section(rules)
        assert "my relay" in out

    def test_render_rules_section_multiple(self):
        from daran_proxy_stack.modules.cascade import render_rules_section
        rules = [
            {"protocol": "tcp", "listen_port": 1000, "target_host": "a", "target_port": 2000, "notes": ""},
            {"protocol": "udp", "listen_port": 1001, "target_host": "b", "target_port": 2001, "notes": ""},
        ]
        out = render_rules_section(rules)
        assert "-p1000" in out
        assert "-p1001" in out
        assert "tcppm" in out
        assert "udppm" in out

    # --- render_3proxy_config with rules ---

    def test_render_3proxy_config_no_rules(self):
        from daran_proxy_stack.modules.cascade import render_3proxy_config
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        out = render_3proxy_config(cfg, rules=None)
        assert "socks" in out
        assert "parent" in out
        assert "tcppm" not in out

    def test_render_3proxy_config_empty_rules(self):
        from daran_proxy_stack.modules.cascade import render_3proxy_config
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        out = render_3proxy_config(cfg, rules=[])
        assert "tcppm" not in out

    def test_render_3proxy_config_with_rules_includes_portmap(self):
        from daran_proxy_stack.modules.cascade import render_3proxy_config
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        rules = [{"protocol": "tcp", "listen_port": 4443, "target_host": "10.0.0.5", "target_port": 443, "notes": ""}]
        out = render_3proxy_config(cfg, rules=rules)
        assert "socks" in out
        assert "parent" in out
        assert "tcppm" in out
        assert "-p4443" in out
        assert "-e10.0.0.5" in out
        assert "-E443" in out

    # --- apply() loads rules from disk and embeds them ---

    def test_apply_no_rules_no_portmap_in_cfg(self, tmp_path):
        from daran_proxy_stack.modules.cascade import apply
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        apply(cfg, tmp_path)
        cfg_text = (tmp_path / "cascade" / "3proxy.cfg").read_text()
        assert "tcppm" not in cfg_text
        assert "udppm" not in cfg_text

    def test_apply_with_rules_embeds_portmap(self, tmp_path):
        from daran_proxy_stack.modules.cascade import apply, add_rule
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        add_rule(tmp_path, protocol="tcp", listen_port=8080, target_host="192.168.1.1", target_port=80)
        apply(cfg, tmp_path)
        cfg_text = (tmp_path / "cascade" / "3proxy.cfg").read_text()
        assert "tcppm" in cfg_text
        assert "-p8080" in cfg_text
        assert "-e192.168.1.1" in cfg_text
        assert "-E80" in cfg_text

    def test_apply_with_rules_state_json_includes_count(self, tmp_path):
        from daran_proxy_stack.modules.cascade import apply, add_rule
        from daran_proxy_stack.lib.models import CascadeConfig
        import json as _json
        cfg = CascadeConfig()
        add_rule(tmp_path, protocol="tcp", listen_port=1111, target_host="h", target_port=2222)
        add_rule(tmp_path, protocol="udp", listen_port=3333, target_host="h", target_port=4444)
        apply(cfg, tmp_path)
        state = _json.loads((tmp_path / "cascade" / "state.json").read_text())
        assert state["rules_count"] == 2

    def test_apply_summary_mentions_rules(self, tmp_path):
        from daran_proxy_stack.modules.cascade import apply, add_rule
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        add_rule(tmp_path, protocol="tcp", listen_port=9999, target_host="x", target_port=1)
        summary = apply(cfg, tmp_path)
        assert "1 managed rule" in summary

    def test_apply_summary_zero_rules(self, tmp_path):
        from daran_proxy_stack.modules.cascade import apply
        from daran_proxy_stack.lib.models import CascadeConfig
        cfg = CascadeConfig()
        summary = apply(cfg, tmp_path)
        assert "0 managed rule" in summary

    # --- apply_config action preview reflects managed rules ---

    def test_apply_config_preview_shows_managed_rules(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=7777, target_host="relay.example.com", target_port=443)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.apply_config(confirmed=False)
        assert not result.ok  # preview, not confirmed
        assert "7777" in result.body
        assert "relay.example.com" in result.body
        assert "tcppm" in result.body  # rules appear in preview cfg text

    def test_apply_config_preview_shows_zero_rules_message(self, tmp_path):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.apply_config(confirmed=False)
        assert "0" in result.body
        assert "Добавьте" in result.body or "добавьте" in result.body

    def test_apply_config_confirmed_with_rules_writes_portmap(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="tcp", listen_port=6543, target_host="exit.node", target_port=1080)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.apply_config(confirmed=True)
        assert result.ok
        cfg_text = (tmp_path / "cascade" / "3proxy.cfg").read_text()
        assert "tcppm" in cfg_text
        assert "-p6543" in cfg_text
        assert "-eexit.node" in cfg_text

    def test_apply_config_confirmed_rules_count_in_summary(self, tmp_path):
        from daran_proxy_stack.modules.cascade import add_rule
        add_rule(tmp_path, protocol="both", listen_port=5432, target_host="db.internal", target_port=5432)
        add_rule(tmp_path, protocol="tcp", listen_port=8888, target_host="api.internal", target_port=80)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.apply_config(confirmed=True)
        assert result.ok
        assert "2" in result.body


# ---------------------------------------------------------------------------
# load_cascade_config — config.yaml integration
# ---------------------------------------------------------------------------

class TestLoadCascadeConfig:
    """Tests for the load_cascade_config() helper and _find_config_yaml() discovery."""

    def test_defaults_when_no_config(self, tmp_path):
        """Returns CascadeConfig() defaults when no config.yaml exists."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_config_yaml",
            return_value=None,
        ):
            cfg, source = cascade_actions.load_cascade_config()
        assert cfg.relay_port == 1080
        assert cfg.upstream_socks_port == 40000
        assert cfg.enabled is False
        assert "defaults" in source

    def test_loads_cascade_from_config_yaml(self, tmp_path):
        """Reads real values from a config.yaml with cascade section."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "cascade:\n"
            "  relay_host: 10.0.0.1\n"
            "  relay_port: 2080\n"
            "  upstream_socks_host: 10.0.0.2\n"
            "  upstream_socks_port: 50000\n"
            "  mode: chain\n"
            "  enabled: true\n",
            encoding="utf-8",
        )
        cfg, source = cascade_actions.load_cascade_config(config_path=config_yaml)
        assert cfg.relay_host == "10.0.0.1"
        assert cfg.relay_port == 2080
        assert cfg.upstream_socks_host == "10.0.0.2"
        assert cfg.upstream_socks_port == 50000
        assert cfg.mode == "chain"
        assert cfg.enabled is True
        assert str(config_yaml) in source

    def test_partial_cascade_section_uses_defaults_for_missing_keys(self, tmp_path):
        """A config.yaml with only some cascade keys falls back to defaults for the rest."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "cascade:\n"
            "  relay_port: 9999\n",
            encoding="utf-8",
        )
        cfg, source = cascade_actions.load_cascade_config(config_path=config_yaml)
        assert cfg.relay_port == 9999
        # Unspecified keys retain model defaults
        assert cfg.relay_host == "127.0.0.1"
        assert cfg.upstream_socks_port == 40000

    def test_malformed_yaml_falls_back_to_defaults(self, tmp_path):
        """Malformed config.yaml triggers fallback to defaults without raising."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("cascade: [not, a, mapping", encoding="utf-8")
        cfg, source = cascade_actions.load_cascade_config(config_path=config_yaml)
        assert cfg.relay_port == 1080
        assert "defaults" in source

    def test_no_cascade_section_uses_defaults(self, tmp_path):
        """A config.yaml without a cascade section yields defaults for cascade."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "warp:\n"
            "  socks_port: 40000\n",
            encoding="utf-8",
        )
        cfg, source = cascade_actions.load_cascade_config(config_path=config_yaml)
        assert cfg.relay_port == 1080
        assert cfg.enabled is False

    def test_apply_config_preview_shows_config_source(self, tmp_path):
        """apply_config preview must mention Источник конфигурации."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            result = cascade_actions.apply_config(confirmed=False)
        assert "Источник конфигурации" in result.body

    def test_apply_config_preview_uses_yaml_values(self, tmp_path):
        """When config.yaml exists, preview shows values from it (not hardcoded defaults)."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "cascade:\n"
            "  relay_host: 192.168.99.1\n"
            "  relay_port: 3333\n"
            "  upstream_socks_host: 192.168.99.2\n"
            "  upstream_socks_port: 4444\n"
            "  mode: forward\n"
            "  enabled: false\n",
            encoding="utf-8",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade._find_config_yaml",
                return_value=config_yaml,
            ):
                result = cascade_actions.apply_config(confirmed=False)
        assert "192.168.99.1" in result.body
        assert "3333" in result.body
        assert "192.168.99.2" in result.body
        assert "4444" in result.body

    def test_apply_config_confirmed_uses_yaml_values(self, tmp_path):
        """When confirmed, artifacts reflect values from config.yaml."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            "cascade:\n"
            "  relay_host: 10.10.10.10\n"
            "  relay_port: 5555\n"
            "  upstream_socks_host: 10.10.10.11\n"
            "  upstream_socks_port: 6666\n"
            "  mode: forward\n"
            "  enabled: true\n",
            encoding="utf-8",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.cascade._find_artifacts_dir",
            return_value=tmp_path,
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.cascade._find_config_yaml",
                return_value=config_yaml,
            ):
                result = cascade_actions.apply_config(confirmed=True)
        assert result.ok
        cfg_text = (tmp_path / "cascade" / "3proxy.cfg").read_text()
        assert "10.10.10.11 6666" in cfg_text  # upstream in parent line
        assert "5555" in cfg_text               # relay port in socks line
        # source shown in result body
        assert "Источник конфигурации" in result.body
