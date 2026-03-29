"""Tests for cli.actions.warp and cli.actions.mtproxy.

All shell calls are mocked — no actual system changes.
"""
from __future__ import annotations

import unittest.mock
from collections import deque
from dataclasses import dataclass

import pytest

from daran_proxy_stack.cli.actions import warp as warp_actions
from daran_proxy_stack.cli.actions import mtproxy as mtproxy_actions


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _make_diag(connected=False, socks_running=False, warp_cli="/usr/bin/warp-cli"):
    from daran_proxy_stack.modules.warp import WarpDiagnostics
    return WarpDiagnostics(
        os_release="Ubuntu 24.04",
        warp_cli_path=warp_cli,
        cloudflared_path=None,
        systemctl_path="/usr/bin/systemctl",
        server_ip="10.0.0.1",
        warp_status="Connected" if connected else "Disconnected",
        recommended_backend="warp-cli",
        connected=connected,
        socks_running=socks_running,
    )


def _make_mtp_diag():
    from daran_proxy_stack.modules.mtproxy import MTProxyDiagnostics
    return MTProxyDiagnostics(
        docker_path="/usr/bin/docker",
        docker_compose_path=None,
        systemctl_path="/usr/bin/systemctl",
        ufw_path=None,
        ss_path="/usr/bin/ss",
        git_path="/usr/bin/git",
        curl_path="/usr/bin/curl",
        make_path="/usr/bin/make",
        gcc_path="/usr/bin/gcc",
        server_ip="10.0.0.1",
        container_status="not installed",
        port_status="free",
        compose_exists=False,
        run_user_exists=True,
    )


# ---------------------------------------------------------------------------
# WARP actions
# ---------------------------------------------------------------------------

class TestWarpActionsStatus:
    def test_status_returns_ok(self):
        diag = _make_diag()
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.collect_diagnostics",
            return_value=diag,
        ):
            result = warp_actions.status()
        assert result.ok
        assert "Ubuntu" in result.body
        assert "warp-cli" in result.body

    def test_status_error_handled(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.collect_diagnostics",
            side_effect=RuntimeError("fail"),
        ):
            result = warp_actions.status()
        assert not result.ok
        assert "fail" in result.body


class TestWarpActionsXray:
    def test_xray_info_ok_when_socks_running(self):
        diag = _make_diag(socks_running=True)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.collect_diagnostics",
            return_value=diag,
        ):
            result = warp_actions.xray_info()
        assert result.ok
        assert "socks" in result.body.lower()

    def test_xray_info_degraded_when_socks_down(self):
        diag = _make_diag(socks_running=False)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.collect_diagnostics",
            return_value=diag,
        ):
            result = warp_actions.xray_info()
        assert not result.ok  # socks not listening
        assert "SOCKS" in result.body


class TestWarpActionsInstall:
    def test_install_unconfirmed_returns_plan(self):
        result = warp_actions.install(confirmed=False)
        assert not result.ok
        assert "Cloudflare" in result.body or "APT" in result.body or "подтверждение" in result.body.lower() or "Будут" in result.body

    def test_install_confirmed_delegates(self):
        from daran_proxy_stack.modules.warp import WarpActionResult
        mock_result = WarpActionResult(True, "WARP install", "installed ok")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.install_warp_cli",
            return_value=mock_result,
        ):
            result = warp_actions.install(confirmed=True)
        assert result.ok

    def test_install_confirmed_fail(self):
        from daran_proxy_stack.modules.warp import WarpActionResult
        mock_result = WarpActionResult(False, "WARP install failed", "some error")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.install_warp_cli",
            return_value=mock_result,
        ):
            result = warp_actions.install(confirmed=True)
        assert not result.ok


class TestWarpActionsConnect:
    def test_connect_unconfirmed(self):
        result = warp_actions.connect(confirmed=False)
        assert not result.ok
        assert "warp-cli" in result.body

    def test_connect_confirmed_ok(self):
        from daran_proxy_stack.modules.warp import WarpActionResult
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.connect_warp",
            return_value=WarpActionResult(True, "WARP connected", "ok"),
        ):
            result = warp_actions.connect(confirmed=True)
        assert result.ok

    def test_connect_unconfirmed_warns_about_ssh(self):
        result = warp_actions.connect(confirmed=False)
        assert "SSH" in result.body


class TestWarpActionsDisconnect:
    def test_disconnect_unconfirmed(self):
        result = warp_actions.disconnect(confirmed=False)
        assert not result.ok

    def test_disconnect_confirmed(self):
        from daran_proxy_stack.modules.warp import WarpActionResult
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.disconnect_warp",
            return_value=WarpActionResult(True, "disconnected", "done"),
        ):
            result = warp_actions.disconnect(confirmed=True)
        assert result.ok


class TestWarpActionsSocks:
    def test_socks_up_unconfirmed(self):
        result = warp_actions.socks_up(confirmed=False)
        assert not result.ok

    def test_socks_up_confirmed(self):
        from daran_proxy_stack.modules.warp import WarpActionResult
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.start_local_socks",
            return_value=WarpActionResult(True, "SOCKS started", "ok"),
        ):
            result = warp_actions.socks_up(confirmed=True)
        assert result.ok

    def test_socks_down_unconfirmed(self):
        result = warp_actions.socks_down(confirmed=False)
        assert not result.ok

    def test_socks_down_confirmed(self):
        from daran_proxy_stack.modules.warp import WarpActionResult
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.stop_local_socks",
            return_value=WarpActionResult(True, "SOCKS stopped", "done"),
        ):
            result = warp_actions.socks_down(confirmed=True)
        assert result.ok


class TestWarpActionsUninstall:
    def test_uninstall_unconfirmed(self):
        result = warp_actions.uninstall(confirmed=False)
        assert not result.ok
        assert "apt" in result.body.lower() or "удалит" in result.body

    def test_uninstall_confirmed_no_cli(self):
        with unittest.mock.patch("shutil.which", return_value=None):
            result = warp_actions.uninstall(confirmed=True)
        assert result.ok
        assert "удалён" in result.body.lower() or "уже удалён" in result.body


# ---------------------------------------------------------------------------
# MTProxy actions
# ---------------------------------------------------------------------------

class TestMTProxyActionsStatus:
    def test_status_ok(self):
        diag = _make_mtp_diag()
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.mtp_mod.collect_diagnostics",
            return_value=diag,
        ):
            result = mtproxy_actions.status()
        assert result.ok
        assert "10.0.0.1" in result.body

    def test_status_error(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.mtp_mod.collect_diagnostics",
            side_effect=RuntimeError("boom"),
        ):
            result = mtproxy_actions.status()
        assert not result.ok
        assert "boom" in result.body


class TestMTProxyActionsInstallGuide:
    def test_install_guide_returns_info(self):
        diag = _make_mtp_diag()
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.mtp_mod.collect_diagnostics",
            return_value=diag,
        ):
            result = mtproxy_actions.install_guide()
        assert result.ok
        assert "MTProxy" in result.body or "official" in result.body.lower()


class TestMTProxyActionsShowTgLink:
    def test_no_artifacts_dir(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._find_generated_dir",
            return_value=None,
        ):
            result = mtproxy_actions.show_tg_link()
        assert not result.ok
        assert "Артефакты" in result.body

    def test_with_tg_link_file(self, tmp_path):
        (tmp_path / "tg-link.txt").write_text("tg://proxy?server=1.2.3.4&port=443&secret=aabbcc")
        (tmp_path / "secret.txt").write_text("aabbcc")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._find_generated_dir",
            return_value=tmp_path,
        ):
            result = mtproxy_actions.show_tg_link()
        assert result.ok
        assert "tg://proxy" in result.body


class TestMTProxyActionsRestart:
    def test_restart_systemd(self):
        from daran_proxy_stack.lib.shell import CommandResult
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._detect_manager",
            return_value=("systemd", "MTProxy"),
        ):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.actions.mtproxy.run",
                return_value=CommandResult("sudo systemctl restart MTProxy", 0, "", ""),
            ):
                result = mtproxy_actions.restart()
        assert result.ok

    def test_restart_no_manager(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._detect_manager",
            return_value=("none", None),
        ):
            result = mtproxy_actions.restart()
        assert not result.ok
        assert "systemctl" in result.body


class TestMTProxyActionsUninstall:
    def test_uninstall_unconfirmed(self):
        result = mtproxy_actions.uninstall(confirmed=False)
        assert not result.ok
        assert "systemctl" in result.body or "удаление" in result.body.lower()

    def test_uninstall_no_manager(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._detect_manager",
            return_value=("none", None),
        ):
            result = mtproxy_actions.uninstall(confirmed=True)
        assert not result.ok
        assert "не обнаружен" in result.body


# ---------------------------------------------------------------------------
# Menu integration: new submenu choices
# ---------------------------------------------------------------------------

class TestMenuWarpSubMenuActions:
    """Smoke-test new WARP menu items go through without crash."""

    def _run(self, choices: list[str]):
        inputs = deque(choices)
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            from daran_proxy_stack.cli.menu import run_menu
            run_menu(input_fn=lambda: inputs.popleft())

    def test_warp_diag_status(self):
        """Choice '2' = system diagnostics — read-only, no confirm."""
        diag_mock = _make_diag()
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.collect_diagnostics",
            return_value=diag_mock,
        ):
            # 3=WARP submenu, 2=diag, 0=back, 0=exit
            self._run(["3", "2", "0", "0"])

    def test_warp_xray_info(self):
        """Choice '9' = Xray JSON."""
        diag_mock = _make_diag(socks_running=True)
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.warp_mod.collect_diagnostics",
            return_value=diag_mock,
        ):
            self._run(["3", "9", "0", "0"])

    def test_warp_install_cancel(self):
        """Choice '3' → install → cancel (n)."""
        self._run(["3", "3", "n", "0", "0"])

    def test_warp_connect_cancel(self):
        """Choice '5' → connect → cancel."""
        self._run(["3", "5", "n", "0", "0"])

    def test_warp_socks_up_cancel(self):
        """Choice '7' → socks up → cancel."""
        self._run(["3", "7", "n", "0", "0"])

    def test_warp_socks_down_cancel(self):
        """Choice '8' → socks down → cancel."""
        self._run(["3", "8", "n", "0", "0"])


class TestMenuMTProxySubMenuActions:
    """Smoke-test new MTProxy menu items."""

    def _run(self, choices: list[str]):
        inputs = deque(choices)
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            from daran_proxy_stack.cli.menu import run_menu
            run_menu(input_fn=lambda: inputs.popleft())

    def test_mtproxy_diag(self):
        """Choice '2' = system diagnostics."""
        diag_mock = _make_mtp_diag()
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.mtp_mod.collect_diagnostics",
            return_value=diag_mock,
        ):
            self._run(["1", "2", "0", "0"])

    def test_mtproxy_install_guide(self):
        """Choice '3' = install guide."""
        diag_mock = _make_mtp_diag()
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.mtp_mod.collect_diagnostics",
            return_value=diag_mock,
        ):
            self._run(["1", "3", "0", "0"])

    def test_mtproxy_tg_link_no_artifacts(self):
        """Choice '6' = tg link, no artifacts."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._find_generated_dir",
            return_value=None,
        ):
            self._run(["1", "6", "0", "0"])

    def test_mtproxy_restart_no_manager(self):
        """Choice '5' = restart, no manager found."""
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy._detect_manager",
            return_value=("none", None),
        ):
            self._run(["1", "5", "0", "0"])

    def test_mtproxy_uninstall_cancel(self):
        """Choice '4' → uninstall → cancel."""
        self._run(["1", "4", "n", "0", "0"])
