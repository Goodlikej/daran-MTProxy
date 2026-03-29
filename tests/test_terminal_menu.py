"""Tests for terminal menu — render helpers and menu loop.

All discovery calls are mocked so tests run fully offline.
"""
from __future__ import annotations

import unittest.mock
from collections import deque

import pytest

from daran_proxy_stack.discovery.schema import (
    DiscoveryConfidence,
    DiscoveryMeta,
    HostState,
    ModuleHealth,
    ModuleManager,
    ObservedState,
)
from daran_proxy_stack.discovery.modules.mtproxy import (
    MTProxyClientArtifacts,
    MTProxyPublicEndpoint,
    MTProxyRuntime,
    MTProxyState,
)
from daran_proxy_stack.discovery.modules.warp import WarpState, WarpRegistration
from daran_proxy_stack.discovery.modules.cascade import CascadeState
from daran_proxy_stack.cli.menu import (
    render_host_summary,
    render_modules_table,
    render_discovery_meta,
    render_module_detail,
    cmd_view_modules,
    run_menu,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_state(
    *,
    warp_health: ModuleHealth = ModuleHealth.not_installed,
    mtproxy_health: ModuleHealth = ModuleHealth.not_installed,
    cascade_health: ModuleHealth = ModuleHealth.not_installed,
    meta_status: str = "ok",
    partial_modules: list[str] | None = None,
) -> ObservedState:
    now = "2026-03-28T10:00:00+00:00"
    warp = WarpState(
        installed=False,
        enabled=False,
        running=False,
        health=warp_health,
        version=None,
        manager=ModuleManager.none,
        last_checked_at=now,
        confidence=DiscoveryConfidence.full,
    )
    mtproxy = MTProxyState(
        installed=False,
        enabled=False,
        running=False,
        health=mtproxy_health,
        version=None,
        manager=ModuleManager.none,
        last_checked_at=now,
        confidence=DiscoveryConfidence.full,
    )
    cascade = CascadeState(
        installed=False,
        enabled=False,
        running=False,
        health=cascade_health,
        version=None,
        manager=ModuleManager.none,
        last_checked_at=now,
        confidence=DiscoveryConfidence.full,
    )
    return ObservedState(
        schema_version="1.0",
        host=HostState(
            os="Ubuntu",
            version="24.04",
            public_ip="1.2.3.4",
            hostname="vps-test",
        ),
        discovery=DiscoveryMeta(
            last_run_at=now,
            status=meta_status,
            partial_modules=partial_modules or [],
        ),
        warp=warp,
        mtproxy=mtproxy,
        cascade=cascade,
    )


# ---------------------------------------------------------------------------
# render_host_summary
# ---------------------------------------------------------------------------

class TestRenderHostSummary:
    def test_contains_hostname(self):
        state = _make_state()
        panel = render_host_summary(state)
        # Panel title is "Host"; renderable content contains hostname
        from rich.console import Console
        from io import StringIO
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(panel)
        out = buf.getvalue()
        assert "vps-test" in out
        assert "1.2.3.4" in out

    def test_unknown_ip_shown(self):
        state = _make_state()
        state.host.public_ip = None
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_host_summary(state))
        assert "unknown" in buf.getvalue()


# ---------------------------------------------------------------------------
# render_modules_table
# ---------------------------------------------------------------------------

class TestRenderModulesTable:
    def test_all_modules_present(self):
        state = _make_state()
        table = render_modules_table(state)
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(table)
        out = buf.getvalue()
        assert "warp" in out
        assert "mtproxy" in out
        assert "cascade" in out

    def test_health_not_installed(self):
        state = _make_state()
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_modules_table(state))
        assert "not_installed" in buf.getvalue()

    def test_healthy_module(self):
        state = _make_state(mtproxy_health=ModuleHealth.healthy)
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_modules_table(state))
        assert "healthy" in buf.getvalue()

    def test_none_module(self):
        state = _make_state()
        state.warp = None  # type: ignore[assignment]
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_modules_table(state))
        # Russian: "нет данных"
        assert "нет данных" in buf.getvalue()


# ---------------------------------------------------------------------------
# render_discovery_meta
# ---------------------------------------------------------------------------

class TestRenderDiscoveryMeta:
    def test_ok_status(self):
        state = _make_state(meta_status="ok")
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_discovery_meta(state))
        assert "ok" in buf.getvalue()

    def test_partial_modules_listed(self):
        state = _make_state(meta_status="partial", partial_modules=["warp", "mtproxy"])
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_discovery_meta(state))
        out = buf.getvalue()
        assert "warp" in out
        assert "mtproxy" in out

    def test_warnings_shown(self):
        state = _make_state()
        state.discovery.warnings = ["something went wrong"]
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(render_discovery_meta(state))
        assert "something went wrong" in buf.getvalue()


# ---------------------------------------------------------------------------
# render_module_detail
# ---------------------------------------------------------------------------

class TestRenderModuleDetail:
    def test_mtproxy_detail_with_endpoint(self):
        now = "2026-03-28T10:00:00+00:00"
        mtproxy = MTProxyState(
            installed=True,
            enabled=True,
            running=True,
            health=ModuleHealth.healthy,
            version="telegrammessenger/proxy",
            manager=ModuleManager.docker,
            last_checked_at=now,
            confidence=DiscoveryConfidence.full,
            public_endpoint=MTProxyPublicEndpoint(ip="1.2.3.4", port=443),
            client_artifacts=MTProxyClientArtifacts(
                tg_link="tg://proxy?server=1.2.3.4&port=443&secret=abc",
                secret_present=True,
                fake_tls_host=None,
            ),
            runtime=MTProxyRuntime(container_name="mtproxy", container_running=True),
        )
        panel = render_module_detail("mtproxy", mtproxy)
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=140, force_terminal=False, no_color=True)
        con.print(panel)
        out = buf.getvalue()
        assert "1.2.3.4" in out
        # Russian: "есть" for secret_present
        assert "есть" in out
        assert "tg://proxy" in out

    def test_none_module_handled(self):
        panel = render_module_detail("warp", None)
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=80, force_terminal=False, no_color=True)
        con.print(panel)
        assert "No data" in buf.getvalue()  # English fallback message

    def test_warp_detail(self):
        now = "2026-03-28T10:00:00+00:00"
        warp = WarpState(
            installed=True,
            enabled=True,
            running=False,
            health=ModuleHealth.stopped,
            version="warp-cli 2023.7.40",
            manager=ModuleManager.systemd,
            backend="warp-cli",
            registration=WarpRegistration(registered=True, account_type="free"),
            last_checked_at=now,
            confidence=DiscoveryConfidence.full,
        )
        panel = render_module_detail("warp", warp)
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        con = Console(file=buf, width=120, force_terminal=False, no_color=True)
        con.print(panel)
        out = buf.getvalue()
        assert "stopped" in out
        assert "warp-cli" in out


# ---------------------------------------------------------------------------
# cmd_view_modules
# ---------------------------------------------------------------------------

class TestCmdViewModules:
    def test_no_state_prints_warning(self, capsys):
        # cmd_view_modules uses rich console — capture via mock
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console") as mock_con:
            cmd_view_modules(None)
            mock_con.print.assert_called_once()
            args, _ = mock_con.print.call_args
            # Russian warning text
            assert "Нет данных" in str(args[0])

    def test_with_state_no_crash(self):
        state = _make_state()
        # Should not raise
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            cmd_view_modules(state)


# ---------------------------------------------------------------------------
# run_menu (loop logic)
# ---------------------------------------------------------------------------

class TestRunMenu:
    def test_exit_on_zero(self):
        """Выбор 0 должен завершить меню без ошибок."""
        inputs = deque(["0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            run_menu(input_fn=lambda: inputs.popleft())

    def test_unknown_choice_then_exit(self):
        """Неизвестный выбор — вывод ошибки, затем выход."""
        inputs = deque(["9", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console") as mock_con:
            run_menu(input_fn=lambda: inputs.popleft())
            all_calls = [str(c) for c in mock_con.print.call_args_list]
            # Russian: "Неизвестный выбор"
            assert any("Неизвестный" in c for c in all_calls)

    def test_rediscover_via_r_key(self):
        """Клавиша 'r' должна вызвать run_discovery()."""
        state = _make_state()
        inputs = deque(["r", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            with unittest.mock.patch(
                "daran_proxy_stack.cli.menu.run_discovery",
                return_value=state,
            ) as mock_disc:
                run_menu(input_fn=lambda: inputs.popleft())
                mock_disc.assert_called_once()

    def test_mtproxy_submenu_opens_and_back(self):
        """Клавиша '1' открывает MTProxy-подменю, '0' возвращает назад."""
        state = _make_state()
        # 1 → enter MTProxy submenu → 0 → back → 0 → exit main menu
        inputs = deque(["1", "0", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            run_menu(input_fn=lambda: inputs.popleft())

    def test_cascade_submenu_opens_and_back(self):
        """Клавиша '2' открывает Cascade-подменю."""
        state = _make_state()
        inputs = deque(["2", "0", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            run_menu(input_fn=lambda: inputs.popleft())

    def test_warp_submenu_opens_and_back(self):
        """Клавиша '3' открывает WARP-подменю."""
        state = _make_state()
        inputs = deque(["3", "0", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            run_menu(input_fn=lambda: inputs.popleft())

    def test_3xui_submenu_opens_and_back(self):
        """Клавиша '4' открывает 3x-ui-подменю."""
        inputs = deque(["4", "0", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            run_menu(input_fn=lambda: inputs.popleft())

    def test_mtproxy_submenu_status_no_state(self):
        """В подменю MTProxy → '1' при отсутствии данных выводит предупреждение."""
        # No state (input_fn provided, so no auto-discovery)
        inputs = deque(["1", "1", "0", "0"])
        with unittest.mock.patch("daran_proxy_stack.cli.menu.console") as mock_con:
            run_menu(input_fn=lambda: inputs.popleft())
            all_calls = [str(c) for c in mock_con.print.call_args_list]
            assert any("Нет данных" in c for c in all_calls)

    def test_eof_exits_cleanly(self):
        """EOFError из input должен завершить меню без исключений."""
        def raise_eof():
            raise EOFError

        with unittest.mock.patch("daran_proxy_stack.cli.menu.console"):
            run_menu(input_fn=raise_eof)  # не должен бросать исключение

    def test_confirm_uses_plain_prompt_without_input_fn(self):
        with unittest.mock.patch("builtins.input", return_value="yes") as mock_input:
            from daran_proxy_stack.cli.menu import _ask_confirm
            assert _ask_confirm(None) is True
            mock_input.assert_called_once()
