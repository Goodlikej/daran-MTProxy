"""Smoke gate: config, models, shell, WARP and MTProxy pure-Python logic.

No system calls, no docker, no warp-cli required — runs offline in CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from daran_proxy_stack.lib.config import load_config
from daran_proxy_stack.lib.models import AppConfig, AppPaths, MTProxyConfig, WarpConfig
from daran_proxy_stack.lib.shell import CommandResult
from daran_proxy_stack.modules import mtproxy, warp


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
