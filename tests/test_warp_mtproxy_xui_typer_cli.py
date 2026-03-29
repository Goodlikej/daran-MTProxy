"""Tests for WARP, MTProxy, and 3x-ui Typer CLI subcommands.

Covers: warp uninstall, mtproxy uninstall, xui status/install/install-pro/restart.
All shell calls and side effects are mocked — no actual system changes.
"""
from __future__ import annotations

import unittest.mock

import pytest
from typer.testing import CliRunner

from daran_proxy_stack.cli.main import app
from daran_proxy_stack.cli.actions.cascade import ActionResult

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(title="T", body="ok", tip="") -> ActionResult:
    return ActionResult(ok=True, title=title, body=body, tip=tip)


def _fail(title="T", body="fail", tip="") -> ActionResult:
    return ActionResult(ok=False, title=title, body=body, tip=tip)


# ---------------------------------------------------------------------------
# CLI group registration smoke tests
# ---------------------------------------------------------------------------

class TestGroupRegistration:
    def test_xui_in_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "xui" in result.output

    def test_xui_subcommands_in_help(self):
        result = runner.invoke(app, ["xui", "--help"])
        assert result.exit_code == 0
        for cmd in ["status", "install", "install-pro", "restart"]:
            assert cmd in result.output

    def test_warp_uninstall_in_help(self):
        result = runner.invoke(app, ["warp", "--help"])
        assert result.exit_code == 0
        assert "uninstall" in result.output

    def test_mtproxy_uninstall_in_help(self):
        result = runner.invoke(app, ["mtproxy", "--help"])
        assert result.exit_code == 0
        assert "uninstall" in result.output


# ---------------------------------------------------------------------------
# xui status
# ---------------------------------------------------------------------------

class TestXuiStatusCmd:
    def test_status_installed_running(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.status",
            return_value=_ok(title="3x-ui: статус", body="Служба active: да"),
        ):
            result = runner.invoke(app, ["xui", "status"])
        assert result.exit_code == 0
        assert "active" in result.output

    def test_status_not_installed(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.status",
            return_value=_fail(title="3x-ui: статус", body="не установлен"),
        ):
            result = runner.invoke(app, ["xui", "status"])
        assert result.exit_code == 0  # status itself never exits non-zero


# ---------------------------------------------------------------------------
# xui install
# ---------------------------------------------------------------------------

class TestXuiInstallCmd:
    def test_dry_run_shows_preview(self):
        preview = _fail(
            title="3x-ui: установка",
            body="Установка выполняется через официальный скрипт",
            tip="Нажмите [y] чтобы скопировать команду в консоль.",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_guide",
            return_value=preview,
        ):
            result = runner.invoke(app, ["xui", "install"], input="n\n")
        assert result.exit_code == 0

    def test_already_installed_exits_ok(self):
        already = _ok(title="3x-ui: установка", body="уже установлен")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_guide",
            return_value=already,
        ):
            result = runner.invoke(app, ["xui", "install"])
        assert result.exit_code == 0
        assert "уже установлен" in result.output

    def test_yes_flag_shows_confirmed_guide(self):
        confirmed_guide = _ok(
            title="3x-ui: инструкция по установке",
            body="Команда установки 3x-ui",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_guide",
            return_value=confirmed_guide,
        ):
            result = runner.invoke(app, ["xui", "install", "--yes"])
        assert result.exit_code == 0
        assert "Команда установки" in result.output


# ---------------------------------------------------------------------------
# xui install-pro
# ---------------------------------------------------------------------------

class TestXuiInstallProCmd:
    def test_dry_run_then_abort(self):
        preview = _fail(
            title="3x-ui (x-ui-pro): предпросмотр установки",
            body="mozaroc/x-ui-pro",
            tip="Нажмите [y]",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_xui_pro_upstream",
            return_value=preview,
        ):
            result = runner.invoke(app, ["xui", "install-pro"], input="n\n")
        assert result.exit_code == 0

    def test_dry_run_then_confirm(self):
        preview = _fail(
            title="3x-ui (x-ui-pro): предпросмотр установки",
            body="mozaroc/x-ui-pro",
            tip="Нажмите [y]",
        )
        success = _ok(title="3x-ui (x-ui-pro): установка завершена", body="Установщик завершён.")
        side_effects = [preview, success]
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_xui_pro_upstream",
            side_effect=side_effects,
        ):
            result = runner.invoke(app, ["xui", "install-pro"], input="y\n")
        assert result.exit_code == 0
        assert "завершён" in result.output

    def test_yes_flag_runs_installer(self):
        success = _ok(title="3x-ui (x-ui-pro): установка завершена", body="Установщик завершён.")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_xui_pro_upstream",
            return_value=success,
        ):
            result = runner.invoke(app, ["xui", "install-pro", "--yes"])
        assert result.exit_code == 0

    def test_yes_flag_failure_exits_nonzero(self):
        failure = _fail(title="3x-ui (x-ui-pro): ошибка установки", body="failed")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.install_xui_pro_upstream",
            return_value=failure,
        ):
            result = runner.invoke(app, ["xui", "install-pro", "--yes"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# xui restart
# ---------------------------------------------------------------------------

class TestXuiRestartCmd:
    def test_restart_ok(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.service_restart",
            return_value=_ok(title="3x-ui: перезапуск", body="ok"),
        ):
            result = runner.invoke(app, ["xui", "restart"])
        assert result.exit_code == 0

    def test_restart_fail_exits_nonzero(self):
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.xui.service_restart",
            return_value=_fail(title="3x-ui: перезапуск не удался", body="unit not found"),
        ):
            result = runner.invoke(app, ["xui", "restart"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# warp uninstall
# ---------------------------------------------------------------------------

class TestWarpUninstallCmd:
    def test_dry_run_then_abort(self):
        preview = _fail(
            title="WARP: удаление",
            body="Будет выполнено: apt-get remove",
            tip="Нажмите [y]",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.uninstall",
            return_value=preview,
        ):
            result = runner.invoke(app, ["warp", "uninstall"], input="n\n")
        assert result.exit_code == 0

    def test_dry_run_then_confirm(self):
        preview = _fail(
            title="WARP: удаление",
            body="Будет выполнено: apt-get remove",
            tip="Нажмите [y]",
        )
        success = _ok(title="WARP: удалён", body="ok")
        side_effects = [preview, success]
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.uninstall",
            side_effect=side_effects,
        ):
            result = runner.invoke(app, ["warp", "uninstall"], input="y\n")
        assert result.exit_code == 0

    def test_yes_flag_skips_confirm(self):
        success = _ok(title="WARP: удалён", body="warp-cli removed")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.uninstall",
            return_value=success,
        ):
            result = runner.invoke(app, ["warp", "uninstall", "--yes"])
        assert result.exit_code == 0

    def test_yes_flag_failure_exits_nonzero(self):
        failure = _fail(title="WARP: удаление не удалось", body="apt failed")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.warp.uninstall",
            return_value=failure,
        ):
            result = runner.invoke(app, ["warp", "uninstall", "--yes"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# mtproxy uninstall
# ---------------------------------------------------------------------------

class TestMtproxyUninstallCmd:
    def test_dry_run_then_abort(self):
        preview = _fail(
            title="MTProxy: удаление",
            body="Будет выполнено: systemctl stop",
            tip="Нажмите [y]",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.uninstall",
            return_value=preview,
        ):
            result = runner.invoke(app, ["mtproxy", "uninstall"], input="n\n")
        assert result.exit_code == 0

    def test_dry_run_then_confirm(self):
        preview = _fail(
            title="MTProxy: удаление",
            body="systemctl stop MTProxy",
            tip="Нажмите [y]",
        )
        success = _ok(title="MTProxy: удалён (systemd)", body="stop: ok\ndisable: ok")
        side_effects = [preview, success]
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.uninstall",
            side_effect=side_effects,
        ):
            result = runner.invoke(app, ["mtproxy", "uninstall"], input="y\n")
        assert result.exit_code == 0

    def test_yes_flag_skips_confirm(self):
        success = _ok(title="MTProxy: удалён (systemd)", body="done")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.uninstall",
            return_value=success,
        ):
            result = runner.invoke(app, ["mtproxy", "uninstall", "--yes"])
        assert result.exit_code == 0

    def test_yes_flag_failure_exits_nonzero(self):
        failure = _fail(title="MTProxy: удаление не удалось", body="failed")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.uninstall",
            return_value=failure,
        ):
            result = runner.invoke(app, ["mtproxy", "uninstall", "--yes"])
        assert result.exit_code != 0

    def test_not_found_exits_ok(self):
        """When no service is detected, uninstall returns not-found message but ok=False."""
        not_found = _fail(title="MTProxy: удаление", body="Сервис не обнаружен")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.uninstall",
            return_value=not_found,
        ):
            result = runner.invoke(app, ["mtproxy", "uninstall", "--yes"])
        # non-zero exit because ok=False, but no crash
        assert result.exit_code != 0
        assert "Сервис не обнаружен" in result.output
class TestMtproxyOfficialInstallCmd:
    def test_busy_443_shows_fallbacks(self):
        conflict = _fail(
            title="MTProxy: конфликт порта",
            body="Порт 443 уже занят. Доступные альтернативные порты: 2053, 2083",
            tip="fallback",
        )
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.install",
            return_value=conflict,
        ):
            result = runner.invoke(app, ["mtproxy", "official-install"], input="\n")
        assert result.exit_code == 2
        assert "2053" in result.output
        assert "2083" in result.output

    def test_yes_flag_uses_backend(self):
        success = _ok(title="MTProxy: установка завершена", body="ok")
        with unittest.mock.patch(
            "daran_proxy_stack.cli.actions.mtproxy.install",
            return_value=success,
        ) as mock_install:
            result = runner.invoke(app, ["mtproxy", "official-install", "--port", "2053", "--yes"])
        assert result.exit_code == 0
        assert mock_install.call_args.kwargs["port"] == 2053
        assert mock_install.call_args.kwargs["confirmed"] is True
