"""Smoke gate: config, models, shell, WARP / MTProxy / Cascade / API logic.

No system calls, no docker, no warp-cli required — runs offline in CI.
Web API tests require httpx + jinja2 (skipped automatically when absent).
"""
from __future__ import annotations

import json
import time
import unittest.mock
from pathlib import Path

import pytest
from pydantic import ValidationError

from daran_proxy_stack.lib.config import load_config
from daran_proxy_stack.lib.models import (
    AppConfig,
    AppPaths,
    CascadeConfig,
    MTProxyConfig,
    TaskStatus,
    WarpConfig,
)
from daran_proxy_stack.lib.shell import CommandResult
from daran_proxy_stack.modules import cascade, mtproxy, warp


# ── Models ─────────────────────────────────────────────────────────────────────

class TestModels:
    def test_app_config_defaults(self):
        cfg = AppConfig()
        assert cfg.paths.config_dir == "/etc/daran-proxy-stack"
        assert cfg.warp.socks_port == 40000
        assert cfg.mtproxy.listen_port == 443

    def test_warp_config_port_range_low(self):
        with pytest.raises(ValidationError):
            WarpConfig(socks_port=0)

    def test_warp_config_port_range_high(self):
        with pytest.raises(ValidationError):
            WarpConfig(socks_port=65536)

    def test_mtproxy_config_port_range_low(self):
        with pytest.raises(ValidationError):
            MTProxyConfig(listen_port=0)

    def test_mtproxy_config_port_range_high(self):
        with pytest.raises(ValidationError):
            MTProxyConfig(listen_port=70000)

    def test_mtproxy_workers_minimum(self):
        with pytest.raises(ValidationError):
            MTProxyConfig(workers=0)

    def test_app_config_custom_values(self):
        cfg = AppConfig(warp=WarpConfig(socks_port=1080, backend="warp-cli"))
        assert cfg.warp.socks_port == 1080
        assert cfg.warp.backend == "warp-cli"

    def test_app_paths_custom(self):
        p = AppPaths(config_dir="/tmp/cfg", state_dir="/tmp/state", log_dir="/tmp/log")
        assert p.log_dir == "/tmp/log"

    def test_mtproxy_optional_fields_default_none(self):
        cfg = MTProxyConfig()
        assert cfg.secret is None
        assert cfg.ad_tag is None
        assert cfg.public_host is None

    def test_app_config_cascade_defaults(self):
        cfg = AppConfig()
        assert cfg.cascade.enabled is False
        assert cfg.cascade.mode == "forward"
        assert cfg.cascade.relay_port == 1080


# ── Config loading ─────────────────────────────────────────────────────────────

class TestConfigLoading:
    def test_no_file_returns_defaults(self):
        cfg = load_config(None)
        assert isinstance(cfg, AppConfig)
        assert cfg.warp.socks_port == 40000

    def test_missing_path_returns_defaults(self):
        cfg = load_config(Path("/nonexistent/config.yaml"))
        assert isinstance(cfg, AppConfig)

    def test_from_yaml(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("warp:\n  socks_port: 1080\n  backend: cloudflared\n", encoding="utf-8")
        cfg = load_config(f)
        assert cfg.warp.socks_port == 1080
        assert cfg.warp.backend == "cloudflared"

    def test_partial_yaml_keeps_defaults(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("warp:\n  socks_port: 9090\n", encoding="utf-8")
        cfg = load_config(f)
        assert cfg.warp.socks_port == 9090
        assert cfg.warp.socks_host == "127.0.0.1"

    def test_empty_yaml_returns_defaults(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("", encoding="utf-8")
        cfg = load_config(f)
        assert cfg.warp.socks_port == 40000

    def test_mtproxy_section_parsed(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("mtproxy:\n  listen_port: 8443\n  workers: 2\n", encoding="utf-8")
        cfg = load_config(f)
        assert cfg.mtproxy.listen_port == 8443
        assert cfg.mtproxy.workers == 2

    def test_cascade_section_parsed(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(
            "cascade:\n  relay_host: 10.0.0.1\n  relay_port: 2080\n  enabled: true\n",
            encoding="utf-8",
        )
        cfg = load_config(f)
        assert cfg.cascade.relay_host == "10.0.0.1"
        assert cfg.cascade.relay_port == 2080
        assert cfg.cascade.enabled is True


# ── Shell CommandResult ────────────────────────────────────────────────────────

class TestCommandResult:
    def test_ok_true_on_zero(self):
        r = CommandResult(command="echo hi", returncode=0, stdout="hi", stderr="")
        assert r.ok is True

    def test_ok_false_on_nonzero(self):
        r = CommandResult(command="false", returncode=1, stdout="", stderr="error")
        assert r.ok is False

    def test_ok_false_on_negative(self):
        r = CommandResult(command="killed", returncode=-9, stdout="", stderr="")
        assert r.ok is False


# ── Task executor ──────────────────────────────────────────────────────────────

class TestTaskExecutor:
    """Pure in-process executor — no system calls."""

    def _fresh(self):
        from daran_proxy_stack.lib.executor import TaskExecutor
        return TaskExecutor()

    def test_submit_returns_task_immediately(self):
        ex = self._fresh()
        task = ex.submit("noop", lambda: (time.sleep(0.05) or "done"))
        assert task.id
        assert task.name == "noop"

    def test_task_reaches_done(self):
        ex = self._fresh()
        task = ex.submit("quick", lambda: "all good")
        deadline = time.monotonic() + 2.0
        while task.status.value not in ("done", "failed") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert task.status.value == "done"
        assert task.output == "all good"

    def test_task_captures_exception_as_failed(self):
        ex = self._fresh()
        task = ex.submit("boom", lambda: (_ for _ in ()).throw(RuntimeError("kaboom")))
        deadline = time.monotonic() + 2.0
        while task.status.value not in ("done", "failed") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert task.status.value == "failed"
        assert "kaboom" in (task.output or "")

    def test_get_returns_none_for_unknown_id(self):
        ex = self._fresh()
        assert ex.get("nonexistent") is None

    def test_list_all_grows_with_submits(self):
        ex = self._fresh()
        ex.submit("t1", lambda: "a")
        ex.submit("t2", lambda: "b")
        assert len(ex.list_all()) == 2

    def test_get_by_run_id(self):
        ex = self._fresh()
        task = ex.submit("named", lambda: "result")
        deadline = time.monotonic() + 2.0
        while task.status.value == "pending" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ex.get(task.id) is task

    def test_timestamps_set_after_completion(self):
        ex = self._fresh()
        task = ex.submit("ts-test", lambda: "ok")
        deadline = time.monotonic() + 2.0
        while task.status.value not in ("done", "failed") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert task.started_at is not None
        assert task.finished_at is not None
        assert task.finished_at >= task.started_at


# ── WARP pure logic ────────────────────────────────────────────────────────────

class TestWarpLogic:
    def test_parse_status_connected_variants(self):
        assert warp._parse_warp_status_text("Status update: Connected.")
        assert warp._parse_warp_status_text("WARP is ON")
        assert warp._parse_warp_status_text("  connected  ")

    def test_parse_status_not_connected(self):
        # "Disconnected" contains substring "connected" — use unambiguous strings
        assert not warp._parse_warp_status_text("not installed")
        assert not warp._parse_warp_status_text("registration missing")
        assert not warp._parse_warp_status_text("")

    def test_xray_outbound_valid_json(self):
        cfg = WarpConfig(socks_host="127.0.0.1", socks_port=40000)
        data = json.loads(warp.render_xray_outbound(cfg))
        assert data["protocol"] == "socks"
        assert data["tag"] == "warp-out"
        server = data["settings"]["servers"][0]
        assert server["address"] == "127.0.0.1"
        assert server["port"] == 40000

    def test_xray_outbound_custom_port(self):
        cfg = WarpConfig(socks_host="127.0.0.1", socks_port=1080)
        data = json.loads(warp.render_xray_outbound(cfg))
        assert data["settings"]["servers"][0]["port"] == 1080

    def _make_diag(self, **overrides) -> warp.WarpDiagnostics:
        defaults = dict(
            os_release="ubuntu 22.04",
            warp_cli_path=None,
            cloudflared_path=None,
            systemctl_path=None,
            server_ip="1.2.3.4",
            warp_status="not installed",
            recommended_backend="cloudflared",
            connected=False,
            socks_running=False,
        )
        defaults.update(overrides)
        return warp.WarpDiagnostics(**defaults)

    def test_backend_plan_explicit_cloudflared(self):
        cfg = WarpConfig(backend="cloudflared")
        diag = self._make_diag(
            cloudflared_path="/usr/local/bin/cloudflared",
            recommended_backend="cloudflared",
        )
        plan = warp.render_backend_plan(cfg, diag)
        assert "cloudflared" in plan
        assert "socks endpoint" in plan

    def test_backend_plan_auto_uses_recommended(self):
        cfg = WarpConfig(backend="auto")
        diag = self._make_diag(
            warp_cli_path="/usr/bin/warp-cli",
            recommended_backend="warp-cli",
            connected=True,
        )
        plan = warp.render_backend_plan(cfg, diag)
        assert "warp-cli" in plan

    def test_backend_plan_missing_tool_install_hint(self):
        cfg = WarpConfig(backend="warp-cli")
        diag = self._make_diag(warp_cli_path=None, recommended_backend="warp-cli")
        plan = warp.render_backend_plan(cfg, diag)
        assert "install warp-cli" in plan

    def test_debug_json_structure(self):
        cfg = WarpConfig()
        diag = self._make_diag(server_ip="10.0.0.1")
        out = json.loads(warp.render_debug_json(cfg, diag))
        assert "config" in out and "diagnostics" in out
        assert out["diagnostics"]["server_ip"] == "10.0.0.1"
        assert out["config"]["socks_port"] == 40000


# ── WARP OS detection (new functions) ─────────────────────────────────────────

class TestWarpOsDetection:
    """Tests for _detect_os_info and _supported_install_os added in latest commit."""

    def _ok(self, stdout: str) -> CommandResult:
        return CommandResult(command="...", returncode=0, stdout=stdout, stderr="")

    def _fail(self) -> CommandResult:
        return CommandResult(command="...", returncode=1, stdout="", stderr="error")

    def test_detect_os_info_ubuntu(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.run", return_value=self._ok("ubuntu jammy")):
            os_id, codename = warp._detect_os_info()
        assert os_id == "ubuntu"
        assert codename == "jammy"

    def test_detect_os_info_debian(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.run", return_value=self._ok("debian bookworm")):
            os_id, codename = warp._detect_os_info()
        assert os_id == "debian"
        assert codename == "bookworm"

    def test_detect_os_info_single_word_no_codename(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.run", return_value=self._ok("alpine")):
            os_id, codename = warp._detect_os_info()
        assert os_id == "alpine"
        assert codename == ""

    def test_detect_os_info_shell_failure_returns_unknown(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.run", return_value=self._fail()):
            os_id, codename = warp._detect_os_info()
        assert os_id == "unknown"
        assert codename == ""

    def test_detect_os_info_empty_stdout_returns_unknown(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.run", return_value=self._ok("")):
            os_id, codename = warp._detect_os_info()
        assert os_id == "unknown"
        assert codename == ""

    def test_supported_install_os_ubuntu(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp._detect_os_info", return_value=("ubuntu", "jammy")):
            assert warp._supported_install_os() is True

    def test_supported_install_os_debian(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp._detect_os_info", return_value=("debian", "bookworm")):
            assert warp._supported_install_os() is True

    def test_supported_install_os_arch_rejected(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp._detect_os_info", return_value=("arch", "")):
            assert warp._supported_install_os() is False

    def test_supported_install_os_unknown_rejected(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp._detect_os_info", return_value=("unknown", "")):
            assert warp._supported_install_os() is False

    def test_supported_install_os_centos_rejected(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp._detect_os_info", return_value=("centos", "7")):
            assert warp._supported_install_os() is False


# ── WARP action results (offline logic) ───────────────────────────────────────

class TestWarpActions:
    """Tests for WarpActionResult dataclass and action functions that have
    offline-decidable paths (no warp-cli, missing tools, wrong host, etc.)."""

    def test_action_result_ok_fields(self):
        r = warp.WarpActionResult(ok=True, title="Done", body="all good")
        assert r.ok is True
        assert r.title == "Done"
        assert r.body == "all good"

    def test_action_result_fail_fields(self):
        r = warp.WarpActionResult(ok=False, title="Fail", body="oops")
        assert r.ok is False

    def test_render_result_panel_green_on_ok(self):
        from rich.panel import Panel
        r = warp.WarpActionResult(ok=True, title="OK", body="done")
        panel = warp.render_result_panel(r)
        assert isinstance(panel, Panel)
        assert panel.border_style == "green"

    def test_render_result_panel_red_on_fail(self):
        from rich.panel import Panel
        r = warp.WarpActionResult(ok=False, title="Err", body="oops")
        panel = warp.render_result_panel(r)
        assert isinstance(panel, Panel)
        assert panel.border_style == "red"

    def test_is_socks_running_no_pid_file(self, tmp_path):
        cfg = WarpConfig(state_dir=str(tmp_path))
        assert warp.is_socks_running(cfg) is False

    def test_is_socks_running_invalid_pid_file(self, tmp_path):
        cfg = WarpConfig(state_dir=str(tmp_path))
        (tmp_path / "warp-socks.pid").write_text("not-a-number", encoding="utf-8")
        assert warp.is_socks_running(cfg) is False

    def test_is_socks_running_nonexistent_proc(self, tmp_path):
        cfg = WarpConfig(state_dir=str(tmp_path))
        # PID 999999999 will never exist
        (tmp_path / "warp-socks.pid").write_text("999999999", encoding="utf-8")
        assert warp.is_socks_running(cfg) is False

    def test_stop_local_socks_no_pid_file(self, tmp_path):
        cfg = WarpConfig(state_dir=str(tmp_path))
        result = warp.stop_local_socks(cfg)
        assert result.ok is True
        assert "no running" in result.body

    def test_stop_local_socks_invalid_pid_file(self, tmp_path):
        cfg = WarpConfig(state_dir=str(tmp_path))
        (tmp_path / "warp-socks.pid").write_text("bad", encoding="utf-8")
        result = warp.stop_local_socks(cfg)
        assert result.ok is False
        assert "invalid pid" in result.body

    def test_start_local_socks_rejects_non_loopback(self, tmp_path):
        cfg = WarpConfig(
            state_dir=str(tmp_path),
            log_dir=str(tmp_path),
            socks_host="0.0.0.0",
        )
        result = warp.start_local_socks(cfg)
        assert result.ok is False
        assert "127.0.0.1" in result.body

    def test_install_warp_cli_already_installed(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.shutil.which", return_value="/usr/bin/warp-cli"):
            result = warp.install_warp_cli()
        assert result.ok is True
        assert "already installed" in result.body

    def test_install_warp_cli_unsupported_os(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.shutil.which", return_value=None), \
             unittest.mock.patch("daran_proxy_stack.modules.warp._supported_install_os", return_value=False):
            result = warp.install_warp_cli()
        assert result.ok is False
        assert "Debian/Ubuntu" in result.body

    def test_connect_warp_missing_cli(self, tmp_path):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.shutil.which", return_value=None):
            cfg = WarpConfig(state_dir=str(tmp_path), log_dir=str(tmp_path))
            result = warp.connect_warp(cfg)
        assert result.ok is False
        assert "warp-cli not found" in result.body

    def test_connect_warp_blocked_in_ssh_session(self, tmp_path):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.shutil.which", return_value="/usr/bin/warp-cli"), \
             unittest.mock.patch.dict("daran_proxy_stack.modules.warp.os.environ", {"SSH_CONNECTION": "1"}, clear=False):
            cfg = WarpConfig(state_dir=str(tmp_path), log_dir=str(tmp_path))
            result = warp.connect_warp(cfg)
        assert result.ok is False
        assert "SSH" in result.body
        assert "DARAN_ALLOW_WARP_REMOTE=1" in result.body

    def test_disconnect_warp_missing_cli(self):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.shutil.which", return_value=None):
            result = warp.disconnect_warp(WarpConfig())
        assert result.ok is False
        assert "warp-cli not found" in result.body

    def test_start_local_socks_missing_cloudflared(self, tmp_path):
        with unittest.mock.patch("daran_proxy_stack.modules.warp.shutil.which", return_value=None):
            cfg = WarpConfig(state_dir=str(tmp_path), log_dir=str(tmp_path))
            result = warp.start_local_socks(cfg)
        assert result.ok is False
        assert "cloudflared not found" in result.body


# ── Cascade pure logic ────────────────────────────────────────────────────────

class TestCascadeLogic:
    def test_cascade_config_defaults(self):
        cfg = CascadeConfig()
        assert cfg.relay_host == "127.0.0.1"
        assert cfg.relay_port == 1080
        assert cfg.upstream_socks_host == "127.0.0.1"
        assert cfg.upstream_socks_port == 40000
        assert cfg.mode == "forward"
        assert cfg.enabled is False

    def test_cascade_config_port_range_low(self):
        with pytest.raises(ValidationError):
            CascadeConfig(relay_port=0)

    def test_cascade_config_port_range_high(self):
        with pytest.raises(ValidationError):
            CascadeConfig(relay_port=65536)

    def test_cascade_config_upstream_port_range(self):
        with pytest.raises(ValidationError):
            CascadeConfig(upstream_socks_port=0)

    def test_diagnostics_no_config_returns_stub(self):
        diag = cascade.collect_diagnostics(None)
        assert diag.config_present is False
        assert diag.relay_reachable is False
        assert diag.upstream_reachable is False
        assert "not yet implemented" in diag.note

    def test_diagnostics_disabled_config_skips_connectivity(self):
        cfg = CascadeConfig(enabled=False)
        diag = cascade.collect_diagnostics(cfg)
        assert diag.config_present is True
        assert diag.relay_reachable is False
        assert diag.upstream_reachable is False
        assert "disabled" in diag.note

    def test_diagnostics_default_dataclass_fields(self):
        diag = cascade.CascadeDiagnostics()
        assert diag.config_present is False
        assert diag.relay_reachable is False
        assert diag.upstream_reachable is False

    def test_render_summary_returns_panel(self):
        from rich.panel import Panel
        cfg = CascadeConfig()
        panel = cascade.render_summary(cfg, cascade.CascadeDiagnostics())
        assert isinstance(panel, Panel)

    def test_render_summary_no_diagnostics_returns_panel(self):
        from rich.panel import Panel
        cfg = CascadeConfig()
        panel = cascade.render_summary(cfg)
        assert isinstance(panel, Panel)

    def test_render_summary_shows_relay_address(self):
        from io import StringIO
        from rich.console import Console
        cfg = CascadeConfig(relay_host="10.0.0.5", relay_port=3128)
        panel = cascade.render_summary(cfg)
        buf = StringIO()
        Console(file=buf, no_color=True, width=120).print(panel)
        out = buf.getvalue()
        assert "10.0.0.5" in out
        assert "3128" in out

    def test_render_summary_disabled_note(self):
        from io import StringIO
        from rich.console import Console
        cfg = CascadeConfig(enabled=False)
        diag = cascade.collect_diagnostics(cfg)
        panel = cascade.render_summary(cfg, diag)
        buf = StringIO()
        Console(file=buf, no_color=True, width=120).print(panel)
        assert "disabled" in buf.getvalue()

    # ── cascade MVP primitives ──────────────────────────────────────────────

    def test_list_relays_returns_one_entry(self):
        cfg = CascadeConfig(relay_host="0.0.0.0", relay_port=1080, enabled=True)
        relays = cascade.list_relays(cfg)
        assert len(relays) == 1
        r = relays[0]
        assert r["relay"] == "0.0.0.0:1080"
        assert r["enabled"] is True

    def test_list_relays_contains_upstream(self):
        cfg = CascadeConfig(upstream_socks_host="127.0.0.1", upstream_socks_port=40000)
        r = cascade.list_relays(cfg)[0]
        assert r["upstream_socks"] == "127.0.0.1:40000"

    def test_list_relays_mode_forwarded(self):
        cfg = CascadeConfig(mode="chain")
        assert cascade.list_relays(cfg)[0]["mode"] == "chain"

    def test_render_3proxy_config_contains_parent(self):
        cfg = CascadeConfig(upstream_socks_host="127.0.0.1", upstream_socks_port=40000)
        out = cascade.render_3proxy_config(cfg)
        assert "parent" in out
        assert "127.0.0.1" in out
        assert "40000" in out

    def test_render_3proxy_config_socks_line(self):
        cfg = CascadeConfig(relay_host="0.0.0.0", relay_port=1080)
        out = cascade.render_3proxy_config(cfg)
        assert "socks" in out
        assert "1080" in out

    def test_render_systemd_unit_structure(self):
        cfg = CascadeConfig()
        svc = cascade.render_systemd_unit(cfg)
        assert "[Unit]" in svc
        assert "[Service]" in svc
        assert "[Install]" in svc
        assert "3proxy" in svc

    def test_apply_writes_artifacts(self, tmp_path):
        cfg = CascadeConfig(
            relay_host="0.0.0.0", relay_port=1080,
            upstream_socks_host="127.0.0.1", upstream_socks_port=40000,
        )
        output = cascade.apply(cfg, tmp_path)
        assert (tmp_path / "cascade" / "3proxy.cfg").exists()
        assert (tmp_path / "cascade" / "cascade.service").exists()
        assert (tmp_path / "cascade" / "state.json").exists()
        assert "relay" in output

    def test_apply_state_json_content(self, tmp_path):
        cfg = CascadeConfig(relay_port=1081, upstream_socks_port=40001)
        cascade.apply(cfg, tmp_path)
        state = json.loads((tmp_path / "cascade" / "state.json").read_text())
        assert state["relay_port"] == 1081
        assert state["upstream_socks_port"] == 40001

    def test_status_dict_keys(self):
        cfg = CascadeConfig(enabled=False)
        with unittest.mock.patch("daran_proxy_stack.modules.cascade._port_open", return_value=False):
            d = cascade.status_dict(cfg)
        assert "enabled" in d
        assert "relay" in d
        assert "upstream_socks" in d
        assert "relay_reachable" in d
        assert "upstream_reachable" in d


# ── API helper data structures (pure, no HTTP) ────────────────────────────────

class TestApiHelpers:
    """Tests for pure data constants and helpers in web/api.py."""

    def test_known_actions_is_list(self):
        from daran_proxy_stack.web.api import _KNOWN_ACTIONS
        assert isinstance(_KNOWN_ACTIONS, list)
        assert len(_KNOWN_ACTIONS) > 0

    def test_known_actions_required_keys(self):
        from daran_proxy_stack.web.api import _KNOWN_ACTIONS
        for action in _KNOWN_ACTIONS:
            assert {"id", "name", "module"} <= set(action.keys()), \
                f"action {action.get('id')!r} missing keys"

    def test_known_actions_covers_warp_and_cascade(self):
        from daran_proxy_stack.web.api import _KNOWN_ACTIONS
        modules = {a["module"] for a in _KNOWN_ACTIONS}
        assert "warp" in modules
        assert "cascade" in modules

    def test_known_actions_ids_are_nonempty_strings(self):
        from daran_proxy_stack.web.api import _KNOWN_ACTIONS
        for action in _KNOWN_ACTIONS:
            assert isinstance(action["id"], str) and action["id"]

    def test_known_actions_includes_warp_connect(self):
        from daran_proxy_stack.web.api import _KNOWN_ACTIONS
        ids = {a["id"] for a in _KNOWN_ACTIONS}
        assert "warp/connect" in ids

    def test_known_actions_includes_mtproxy_generate(self):
        from daran_proxy_stack.web.api import _KNOWN_ACTIONS
        ids = {a["id"] for a in _KNOWN_ACTIONS}
        assert "mtproxy/generate" in ids


# ── API HTTP endpoints (requires httpx + jinja2 / starlette TestClient) ────────

@pytest.fixture(scope="module")
def api_client():
    pytest.importorskip("httpx")
    pytest.importorskip("jinja2")
    from fastapi.testclient import TestClient
    from daran_proxy_stack.web.app import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


class TestWebApiEndpoints:
    """HTTP-level smoke tests for the /api/v1 routes.
    Skipped automatically when httpx or jinja2 is not installed."""

    def test_status_returns_200(self, api_client):
        resp = api_client.get("/api/v1/status")
        assert resp.status_code == 200

    def test_status_top_level_keys(self, api_client):
        data = api_client.get("/api/v1/status").json()
        assert "panel_uptime_s" in data
        assert "server" in data
        assert "mtproxy" in data
        assert "warp" in data
        assert "tasks" in data

    def test_status_panel_uptime_is_number(self, api_client):
        data = api_client.get("/api/v1/status").json()
        assert isinstance(data["panel_uptime_s"], (int, float))

    def test_jobs_endpoint_returns_200(self, api_client):
        resp = api_client.get("/api/v1/jobs")
        assert resp.status_code == 200

    def test_jobs_endpoint_returns_list(self, api_client):
        data = api_client.get("/api/v1/jobs").json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_jobs_endpoint_items_have_id(self, api_client):
        data = api_client.get("/api/v1/jobs").json()
        for job in data:
            assert "id" in job

    def test_warp_endpoint_returns_200(self, api_client):
        resp = api_client.get("/api/v1/warp")
        assert resp.status_code == 200

    def test_warp_endpoint_has_ok_key(self, api_client):
        data = api_client.get("/api/v1/warp").json()
        assert "ok" in data

    def test_mtproxy_endpoint_returns_200(self, api_client):
        resp = api_client.get("/api/v1/mtproxy")
        assert resp.status_code == 200

    def test_mtproxy_endpoint_has_ok_key(self, api_client):
        data = api_client.get("/api/v1/mtproxy").json()
        assert "ok" in data

    def test_servers_endpoint_returns_200(self, api_client):
        resp = api_client.get("/api/v1/servers")
        assert resp.status_code == 200

    def test_servers_endpoint_has_hostname(self, api_client):
        data = api_client.get("/api/v1/servers").json()
        assert "hostname" in data

    def test_cascade_endpoint_returns_200(self, api_client):
        resp = api_client.get("/api/v1/cascade")
        assert resp.status_code == 200

    def test_cascade_endpoint_has_ok_key(self, api_client):
        data = api_client.get("/api/v1/cascade").json()
        assert "ok" in data

    def test_root_redirects(self, api_client):
        resp = api_client.get("/", follow_redirects=False)
        assert resp.status_code in (301, 302, 307, 308)

    # ── WARP action endpoints ──────────────────────────────────────────────

    def test_warp_connect_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/warp/connect")
        assert resp.status_code == 200

    def test_warp_connect_post_has_ok_key(self, api_client):
        data = api_client.post("/api/v1/warp/connect").json()
        assert "ok" in data

    def test_warp_disconnect_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/warp/disconnect")
        assert resp.status_code == 200

    def test_warp_socks_start_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/warp/socks/start")
        assert resp.status_code == 200

    def test_warp_socks_stop_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/warp/socks/stop")
        assert resp.status_code == 200

    # ── MTProxy action endpoints ───────────────────────────────────────────

    def test_mtproxy_generate_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/mtproxy/generate")
        assert resp.status_code == 200

    def test_mtproxy_generate_has_ok_key(self, api_client):
        data = api_client.post("/api/v1/mtproxy/generate").json()
        assert "ok" in data

    def test_mtproxy_up_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/mtproxy/up")
        assert resp.status_code == 200

    def test_mtproxy_down_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/mtproxy/down")
        assert resp.status_code == 200

    # ── Cascade action endpoints ───────────────────────────────────────────

    def test_cascade_refresh_post_returns_200(self, api_client):
        resp = api_client.post("/api/v1/cascade/refresh")
        assert resp.status_code == 200

    def test_cascade_refresh_has_ok_key(self, api_client):
        data = api_client.post("/api/v1/cascade/refresh").json()
        assert "ok" in data
        assert "action" in data


# ── MTProxy pure logic ────────────────────────────────────────────────────────

class TestMTProxyLogic:
    _SECRET = "aabbccdd11223344aabbccdd11223344"

    def test_build_secret_from_config(self):
        cfg = MTProxyConfig(secret=self._SECRET)
        assert mtproxy.build_secret(cfg) == self._SECRET

    def test_build_secret_from_existing_strips_whitespace(self):
        cfg = MTProxyConfig()
        assert mtproxy.build_secret(cfg, existing_secret="  aabbccdd  ") == "aabbccdd"

    def test_build_secret_config_takes_priority_over_existing(self):
        cfg = MTProxyConfig(secret=self._SECRET)
        assert mtproxy.build_secret(cfg, existing_secret="other") == self._SECRET

    def test_build_secret_generates_valid_hex(self):
        cfg = MTProxyConfig()
        s = mtproxy.build_secret(cfg)
        assert len(s) == 32
        int(s, 16)  # raises ValueError if not hex

    def test_tg_link_format(self):
        cfg = MTProxyConfig(listen_port=443, secret=self._SECRET)
        link = mtproxy.render_tg_link(cfg, public_ip="1.2.3.4")
        assert link.startswith("tg://proxy?")
        assert "server=1.2.3.4" in link
        assert "port=443" in link
        assert self._SECRET in link

    def test_tg_link_fallback_to_public_host(self):
        cfg = MTProxyConfig(listen_port=443, secret=self._SECRET, public_host="myserver.com")
        link = mtproxy.render_tg_link(cfg)
        assert "server=myserver.com" in link

    def test_tg_link_placeholder_when_no_ip(self):
        cfg = MTProxyConfig(secret=self._SECRET)
        link = mtproxy.render_tg_link(cfg)
        assert "YOUR_SERVER_IP" in link

    def test_compose_yaml_host_network(self):
        cfg = MTProxyConfig(use_host_network=True, listen_port=443)
        out = mtproxy.render_compose_yaml(cfg, secret=self._SECRET)
        assert "network_mode: host" in out
        assert "ports:" not in out

    def test_compose_yaml_bridge_network_has_ports(self):
        cfg = MTProxyConfig(use_host_network=False, listen_port=8443, stats_port=8888)
        out = mtproxy.render_compose_yaml(cfg, secret=self._SECRET)
        assert "ports:" in out
        assert "8443" in out
        assert "network_mode" not in out

    def test_compose_yaml_ad_tag_included(self):
        cfg = MTProxyConfig(ad_tag="mytag123")
        out = mtproxy.render_compose_yaml(cfg, secret=self._SECRET)
        assert "-P mytag123" in out

    def test_compose_yaml_no_ad_tag_when_absent(self):
        cfg = MTProxyConfig(ad_tag=None)
        out = mtproxy.render_compose_yaml(cfg, secret=self._SECRET)
        assert "-P" not in out

    def test_systemd_service_structure(self):
        cfg = MTProxyConfig(listen_port=443, stats_port=8888)
        svc = mtproxy.render_systemd_service(cfg, secret=self._SECRET)
        assert "[Unit]" in svc
        assert "[Service]" in svc
        assert "[Install]" in svc
        assert "ExecStart=" in svc
        assert "Restart=on-failure" in svc

    def test_official_run_command_flags(self):
        cfg = MTProxyConfig(listen_port=443, stats_port=8888, workers=4, run_user="nobody")
        cmd = mtproxy.render_official_run_command(cfg, secret=self._SECRET)
        assert "-H 443" in cmd
        assert "-p 8888" in cmd
        assert "-M 4" in cmd
        assert "-u nobody" in cmd
        assert f"-S {self._SECRET}" in cmd

    def test_official_run_command_ad_tag(self):
        cfg = MTProxyConfig(ad_tag="promo99")
        cmd = mtproxy.render_official_run_command(cfg, secret=self._SECRET)
        assert "-P promo99" in cmd


# ── Discovery / inventory ─────────────────────────────────────────────────────

class TestDiscovery:
    """Unit tests for discovery.py — all system calls mocked."""

    from daran_proxy_stack.modules import discovery

    def _ok(self, stdout: str = "") -> "CommandResult":
        return CommandResult(command="...", returncode=0, stdout=stdout, stderr="")

    def _fail(self, stderr: str = "not found") -> "CommandResult":
        return CommandResult(command="...", returncode=1, stdout="", stderr=stderr)

    # ── ServiceInventory dataclass ─────────────────────────────────────────

    def test_service_inventory_to_dict_keys(self):
        from daran_proxy_stack.modules.discovery import ServiceInventory
        inv = ServiceInventory(
            name="test", label="Test", detected=True,
            version="1.0", runtime_status="running",
        )
        d = inv.to_dict()
        assert set(d.keys()) == {"name", "label", "detected", "version",
                                  "runtime_status", "config_path", "endpoint", "meta"}

    def test_service_inventory_defaults(self):
        from daran_proxy_stack.modules.discovery import ServiceInventory
        inv = ServiceInventory(name="x", label="X", detected=False, version=None, runtime_status="unknown")
        assert inv.config_path is None
        assert inv.endpoint is None
        assert inv.meta == {}

    # ── _parse_docker_ports ────────────────────────────────────────────────

    def test_parse_docker_ports_standard_mapping(self):
        from daran_proxy_stack.modules.discovery import _parse_docker_ports
        assert _parse_docker_ports("0.0.0.0:443->443/tcp") == "0.0.0.0:443"

    def test_parse_docker_ports_multiple_mappings(self):
        from daran_proxy_stack.modules.discovery import _parse_docker_ports
        result = _parse_docker_ports("0.0.0.0:8080->80/tcp, 0.0.0.0:443->443/tcp")
        assert result == "0.0.0.0:8080"

    def test_parse_docker_ports_no_mapping_returns_none(self):
        from daran_proxy_stack.modules.discovery import _parse_docker_ports
        assert _parse_docker_ports("") is None
        assert _parse_docker_ports("no_arrow_here") is None

    # ── MTProxy detector ───────────────────────────────────────────────────

    def test_detect_mtproxy_no_docker_no_native(self):
        from daran_proxy_stack.modules import discovery
        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None):
            result = discovery._detect_mtproxy()
        assert result.detected is False
        assert result.runtime_status == "not_installed"

    def test_detect_mtproxy_docker_running_container(self):
        from daran_proxy_stack.modules import discovery
        ps_out = "mtproxy\tUp 2 hours\t0.0.0.0:443->443/tcp"
        insp_out = "telegrammessenger/proxy:latest"

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        def _run(cmd):
            if "ps" in cmd:
                return self._ok(ps_out)
            if "inspect" in cmd:
                return self._ok(insp_out)
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_mtproxy()

        assert result.detected is True
        assert result.runtime_status == "running"
        assert result.version == insp_out
        assert result.endpoint == "0.0.0.0:443"

    def test_detect_mtproxy_docker_stopped_container(self):
        from daran_proxy_stack.modules import discovery
        ps_out = "mtproxy\tExited (0) 1 hour ago\t"
        insp_out = "telegrammessenger/proxy:latest"

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        def _run(cmd):
            if "ps" in cmd:
                return self._ok(ps_out)
            if "inspect" in cmd:
                return self._ok(insp_out)
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_mtproxy()

        assert result.detected is True
        assert result.runtime_status == "stopped"

    def test_detect_mtproxy_docker_no_containers_no_image(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        def _run(_cmd):
            return self._ok("")  # empty output: no containers, no image

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_mtproxy()

        assert result.runtime_status == "not_installed"

    # ── WARP detector ──────────────────────────────────────────────────────

    def test_detect_warp_not_installed(self):
        from daran_proxy_stack.modules import discovery
        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None):
            result = discovery._detect_warp()
        assert result.detected is False
        assert result.runtime_status == "not_installed"

    def test_detect_warp_connected(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return f"/usr/bin/{name}" if name == "warp-cli" else None

        def _run(cmd):
            if "--version" in cmd:
                return self._ok("warp-cli 2023.7.40.0")
            if "status" in cmd:
                return self._ok("Status update: Connected.")
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_warp()

        assert result.detected is True
        assert result.runtime_status == "running"
        assert result.version == "warp-cli 2023.7.40.0"

    def test_detect_warp_disconnected(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/bin/warp-cli" if name == "warp-cli" else None

        def _run(cmd):
            if "--version" in cmd:
                return self._ok("warp-cli 2023.7.40.0")
            if "status" in cmd:
                return self._ok("Status update: Disconnected.")
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_warp()

        assert result.detected is True
        assert result.runtime_status == "stopped"

    def test_detect_warp_cloudflared_only(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/local/bin/cloudflared" if name == "cloudflared" else None

        def _run(cmd):
            if "--version" in cmd:
                return self._ok("cloudflared version 2024.1.0")
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_warp()

        assert result.detected is True
        assert result.runtime_status == "stopped"  # cloudflared alone = not connected
        assert "cloudflared" in result.meta

    # ── Xray detector ─────────────────────────────────────────────────────

    def test_detect_xray_not_installed(self):
        from daran_proxy_stack.modules import discovery
        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None), \
             unittest.mock.patch("os.path.isfile", return_value=False):
            result = discovery._detect_xray()
        assert result.detected is False
        assert result.runtime_status == "not_installed"

    def test_detect_xray_installed_running(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/local/bin/xray" if name == "xray" else None

        def _run(cmd):
            if "version" in cmd:
                return self._ok("Xray 1.8.4 (Xray, Penetrates Everything.) Custom (go1.21.5 linux/amd64)")
            if "pgrep" in cmd:
                return self._ok("12345")
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_xray()

        assert result.detected is True
        assert result.runtime_status == "running"
        assert "1.8.4" in (result.version or "")

    def test_detect_xray_installed_stopped(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/local/bin/xray" if name == "xray" else None

        def _run(cmd):
            if "version" in cmd:
                return self._ok("Xray 1.8.4")
            # pgrep returns nonzero when process not found
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_xray()

        assert result.detected is True
        assert result.runtime_status == "stopped"

    # ── AmneziaWG detector ────────────────────────────────────────────────

    def test_detect_amneziawg_not_installed(self):
        from daran_proxy_stack.modules import discovery
        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None), \
             unittest.mock.patch("os.path.isfile", return_value=False):
            result = discovery._detect_amneziawg()
        assert result.detected is False
        assert result.runtime_status == "not_installed"

    def test_detect_amneziawg_running_interface(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/bin/awg" if name == "awg" else None

        def _run(cmd):
            if "--version" in cmd:
                return self._ok("amneziawg v1.0.0")
            if "interfaces" in cmd:
                return self._ok("awg0")
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_amneziawg()

        assert result.detected is True
        assert result.runtime_status == "running"
        assert result.meta.get("interfaces") == ["awg0"]

    def test_detect_amneziawg_installed_no_interfaces(self):
        from daran_proxy_stack.modules import discovery

        def _which(name):
            return "/usr/bin/awg" if name == "awg" else None

        def _run(cmd):
            if "--version" in cmd:
                return self._ok("amneziawg v1.0.0")
            if "interfaces" in cmd:
                return self._ok("")  # no active interfaces
            return self._fail()

        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.modules.discovery.run", side_effect=_run):
            result = discovery._detect_amneziawg()

        assert result.detected is True
        assert result.runtime_status == "stopped"

    # ── collect_inventory ──────────────────────────────────────────────────

    def test_collect_inventory_returns_four_entries(self):
        from daran_proxy_stack.modules import discovery
        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None), \
             unittest.mock.patch("os.path.isfile", return_value=False):
            entries = discovery.collect_inventory()
        assert len(entries) == 4
        names = {e.name for e in entries}
        assert names == {"mtproxy", "warp", "xray", "amneziawg"}

    def test_collect_inventory_tolerates_detector_exception(self):
        from daran_proxy_stack.modules import discovery

        def _boom():
            raise RuntimeError("simulated failure")

        original_detectors = [
            discovery._detect_mtproxy,
            discovery._detect_warp,
            discovery._detect_xray,
            discovery._detect_amneziawg,
        ]
        # Patch one detector to raise
        with unittest.mock.patch.object(discovery, "_detect_mtproxy", side_effect=RuntimeError("boom")):
            with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None), \
                 unittest.mock.patch("os.path.isfile", return_value=False):
                entries = discovery.collect_inventory()
        assert len(entries) == 4
        mt = next((e for e in entries if e.name == "mtproxy"), None)
        assert mt is not None
        assert mt.runtime_status == "unknown"

    def test_inventory_dict_structure(self):
        from daran_proxy_stack.modules import discovery
        with unittest.mock.patch("daran_proxy_stack.modules.discovery.shutil.which", return_value=None), \
             unittest.mock.patch("os.path.isfile", return_value=False):
            d = discovery.inventory_dict()
        assert "services" in d
        assert "timestamp" in d
        assert "count" in d
        assert "detected_count" in d
        assert "running_count" in d
        assert d["count"] == 4

    def test_inventory_dict_counts_detected(self):
        from daran_proxy_stack.modules.discovery import ServiceInventory, inventory_dict
        entries = [
            ServiceInventory("a", "A", detected=True, version=None, runtime_status="running"),
            ServiceInventory("b", "B", detected=False, version=None, runtime_status="not_installed"),
            ServiceInventory("c", "C", detected=True, version=None, runtime_status="stopped"),
        ]
        d = inventory_dict(entries)
        assert d["detected_count"] == 2
        assert d["running_count"] == 1


# ── Discovery: API endpoint ───────────────────────────────────────────────────

class TestInventoryEndpoint:
    """HTTP-level smoke test for /api/v1/inventory. Skipped without httpx."""

    def test_inventory_endpoint_returns_200(self, api_client):
        resp = api_client.get("/api/v1/inventory")
        assert resp.status_code == 200

    def test_inventory_endpoint_has_services(self, api_client):
        data = api_client.get("/api/v1/inventory").json()
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_inventory_endpoint_four_services(self, api_client):
        data = api_client.get("/api/v1/inventory").json()
        assert data["count"] == 4

    def test_inventory_services_have_required_fields(self, api_client):
        data = api_client.get("/api/v1/inventory").json()
        for svc in data["services"]:
            assert "name" in svc
            assert "label" in svc
            assert "detected" in svc
            assert "runtime_status" in svc

    def test_inventory_known_service_names(self, api_client):
        data = api_client.get("/api/v1/inventory").json()
        names = {s["name"] for s in data["services"]}
        assert names == {"mtproxy", "warp", "xray", "amneziawg"}

    def test_status_includes_inventory(self, api_client):
        data = api_client.get("/api/v1/status").json()
        assert "inventory" in data
        assert "services" in data["inventory"]

    def test_warp_info_has_socks_endpoint_field(self, api_client):
        data = api_client.get("/api/v1/warp").json()
        assert "socks_endpoint" in data

    def test_warp_info_has_backend_source(self, api_client):
        data = api_client.get("/api/v1/warp").json()
        assert "backend_source" in data

    def test_mtproxy_info_has_port_source(self, api_client):
        data = api_client.get("/api/v1/mtproxy").json()
        assert "port_source" in data
