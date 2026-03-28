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
# xui.install_guide()
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
        """Choice '2' → install guide → cancel."""
        with self._patch_xui_detect():
            self._run(["4", "2", "n", "0", "0"])

    def test_xui_install_confirm_shows_instructions(self):
        """Choice '2' → install guide → confirm."""
        with self._patch_xui_detect():
            self._run(["4", "2", "y", "0", "0"])

    def test_xui_restart_no_systemctl(self):
        """Choice '3' = restart, no systemctl."""
        with unittest.mock.patch("shutil.which", return_value=None):
            self._run(["4", "3", "0", "0"])
