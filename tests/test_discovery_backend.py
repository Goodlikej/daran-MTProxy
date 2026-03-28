"""Smoke tests for the discovery backend MVP.

All system calls are mocked — tests run fully offline, no docker, no warp-cli.
"""
from __future__ import annotations

import unittest.mock
from datetime import datetime, timezone

import pytest

from daran_proxy_stack.lib.shell import CommandResult
from daran_proxy_stack.discovery.schema import (
    DiscoveryConfidence,
    ModuleHealth,
    ModuleManager,
    ObservedState,
    PortProtocol,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(command="...", returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "not found") -> CommandResult:
    return CommandResult(command="...", returncode=1, stdout="", stderr=stderr)


# ---------------------------------------------------------------------------
# Schema / dataclass tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_module_health_values(self):
        assert ModuleHealth.healthy.value == "healthy"
        assert ModuleHealth.not_installed.value == "not_installed"

    def test_module_manager_values(self):
        assert ModuleManager.docker.value == "docker"
        assert ModuleManager.systemd.value == "systemd"

    def test_port_protocol_values(self):
        assert PortProtocol.tcp.value == "tcp"
        assert PortProtocol.both.value == "both"

    def test_discovery_confidence_values(self):
        assert DiscoveryConfidence.full.value == "full"
        assert DiscoveryConfidence.partial.value == "partial"
        assert DiscoveryConfidence.none.value == "none"

    def test_port_entry_to_dict(self):
        from daran_proxy_stack.discovery.schema import PortEntry
        p = PortEntry(bind="0.0.0.0", port=443, protocol=PortProtocol.tcp, purpose="test")
        d = p.to_dict()
        assert d["bind"] == "0.0.0.0"
        assert d["port"] == 443
        assert d["protocol"] == "tcp"
        assert d["purpose"] == "test"

    def test_host_state_to_dict(self):
        from daran_proxy_stack.discovery.schema import HostState
        h = HostState(os="ubuntu", version="24.04", public_ip="1.2.3.4", hostname="node-1")
        d = h.to_dict()
        assert d["os"] == "ubuntu"
        assert d["version"] == "24.04"
        assert d["public_ip"] == "1.2.3.4"
        assert d["hostname"] == "node-1"

    def test_discovery_meta_to_dict(self):
        from daran_proxy_stack.discovery.schema import DiscoveryMeta
        m = DiscoveryMeta(last_run_at="2026-01-01T00:00:00Z", status="ok")
        d = m.to_dict()
        assert d["status"] == "ok"
        assert d["warnings"] == []
        assert d["partial_modules"] == []


# ---------------------------------------------------------------------------
# Host discovery
# ---------------------------------------------------------------------------

class TestHostDiscovery:
    def test_discover_host_returns_host_state(self):
        from daran_proxy_stack.discovery.host import discover_host, HostState
        with unittest.mock.patch("daran_proxy_stack.discovery.host.run", return_value=_ok("ubuntu\t24.04")), \
             unittest.mock.patch("daran_proxy_stack.discovery.host._detect_public_ip", return_value="1.2.3.4"), \
             unittest.mock.patch("socket.gethostname", return_value="node-1"), \
             unittest.mock.patch("daran_proxy_stack.discovery.host._detect_bbr", return_value=True):
            host = discover_host()
        assert isinstance(host, HostState)
        assert host.os == "ubuntu"
        assert host.version == "24.04"
        assert host.public_ip == "1.2.3.4"
        assert host.hostname == "node-1"
        assert host.bbr_enabled is True

    def test_discover_host_tolerates_all_failures(self):
        from daran_proxy_stack.discovery.host import discover_host
        with unittest.mock.patch("daran_proxy_stack.discovery.host.run", return_value=_fail()), \
             unittest.mock.patch("daran_proxy_stack.discovery.host._detect_public_ip", side_effect=Exception("timeout")), \
             unittest.mock.patch("socket.gethostname", side_effect=OSError("no name")), \
             unittest.mock.patch("daran_proxy_stack.discovery.host._detect_bbr", side_effect=Exception("no sysctl")):
            host = discover_host()
        assert host.os == "unknown"
        assert host.public_ip is None
        assert host.hostname == "unknown"
        assert host.bbr_enabled is None

    def test_bbr_detection_true(self):
        from daran_proxy_stack.discovery.host import _detect_bbr
        with unittest.mock.patch("daran_proxy_stack.discovery.host.run",
                                  return_value=_ok("net.ipv4.tcp_congestion_control = bbr")):
            assert _detect_bbr() is True

    def test_bbr_detection_false(self):
        from daran_proxy_stack.discovery.host import _detect_bbr
        with unittest.mock.patch("daran_proxy_stack.discovery.host.run",
                                  return_value=_ok("net.ipv4.tcp_congestion_control = cubic")):
            assert _detect_bbr() is False

    def test_bbr_detection_none_on_failure(self):
        from daran_proxy_stack.discovery.host import _detect_bbr
        with unittest.mock.patch("daran_proxy_stack.discovery.host.run", return_value=_fail()):
            assert _detect_bbr() is None

    def test_looks_like_ip_valid(self):
        from daran_proxy_stack.discovery.host import _looks_like_ip
        assert _looks_like_ip("1.2.3.4") is True
        assert _looks_like_ip("192.168.1.100") is True
        assert _looks_like_ip("0.0.0.0") is True

    def test_looks_like_ip_invalid(self):
        from daran_proxy_stack.discovery.host import _looks_like_ip
        assert _looks_like_ip("not-an-ip") is False
        assert _looks_like_ip("256.0.0.1") is False
        assert _looks_like_ip("") is False


# ---------------------------------------------------------------------------
# WARP detection
# ---------------------------------------------------------------------------

class TestWarpDetection:
    def test_not_installed(self):
        from daran_proxy_stack.discovery.modules.warp import detect_warp
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.shutil.which",
                                  return_value=None):
            state = detect_warp()
        assert state.installed is False
        assert state.health == ModuleHealth.not_installed
        assert state.confidence == DiscoveryConfidence.full

    def test_healthy_connected_socks_listening(self):
        from daran_proxy_stack.discovery.modules.warp import detect_warp

        def _which(name):
            return f"/usr/bin/{name}" if name == "warp-cli" else None

        def _run(cmd):
            if "--version" in cmd:
                return _ok("warp-cli 2023.7.40.0")
            if "status" in cmd:
                return _ok("Status update: Connected.")
            if "is-active" in cmd or "is-enabled" in cmd:
                return _ok()
            return _fail()

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.run",
                                  side_effect=_run), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_socks5_listen",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_warp_egress_ip",
                                  return_value="8.8.8.8"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_server_ip",
                                  return_value="1.2.3.4"):
            state = detect_warp()

        assert state.installed is True
        assert state.running is True
        assert state.health == ModuleHealth.healthy
        assert state.version == "warp-cli 2023.7.40.0"
        assert len(state.ports) == 1
        assert state.ports[0].purpose == "local-socks5"
        assert state.network is not None
        assert state.network.egress_changed is True  # 8.8.8.8 != 1.2.3.4
        assert state.xray_artifacts is not None

    def test_degraded_connected_but_no_socks(self):
        from daran_proxy_stack.discovery.modules.warp import detect_warp

        def _which(name):
            return "/usr/bin/warp-cli" if name == "warp-cli" else None

        def _run(cmd):
            if "--version" in cmd:
                return _ok("warp-cli 2023.7.40.0")
            if "status" in cmd:
                return _ok("Status update: Connected.")
            return _fail()

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.run",
                                  side_effect=_run), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_socks5_listen",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_warp_egress_ip",
                                  return_value="8.8.8.8"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_server_ip",
                                  return_value="1.2.3.4"):
            state = detect_warp()

        assert state.health == ModuleHealth.degraded
        assert any("SOCKS5" in w for w in state.warnings)

    def test_stopped_disconnected_no_socks(self):
        from daran_proxy_stack.discovery.modules.warp import detect_warp

        def _which(name):
            return "/usr/bin/warp-cli" if name == "warp-cli" else None

        def _run(cmd):
            if "--version" in cmd:
                return _ok("warp-cli 2023.7.40.0")
            if "status" in cmd:
                return _ok("Status update: Disconnected.")
            return _fail()

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.run",
                                  side_effect=_run), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_socks5_listen",
                                  return_value=False):
            state = detect_warp()

        assert state.health == ModuleHealth.stopped
        assert state.installed is True

    def test_xray_outbound_json_is_valid(self):
        import json
        from daran_proxy_stack.discovery.modules.warp import detect_warp

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.shutil.which",
                                  return_value="/usr/bin/warp-cli"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.run",
                                  return_value=_ok("warp-cli 2023.7.40.0")), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.warp._detect_socks5_listen",
                                  return_value=False):
            state = detect_warp()

        assert state.xray_artifacts is not None
        data = json.loads(state.xray_artifacts.socks_outbound_json)
        assert data["protocol"] == "socks"
        assert data["tag"] == "warp-out"
        assert data["settings"]["servers"][0]["port"] == 40000

    def test_to_dict_structure(self):
        from daran_proxy_stack.discovery.modules.warp import detect_warp

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.warp.shutil.which",
                                  return_value=None):
            state = detect_warp()

        d = state.to_dict()
        assert "installed" in d
        assert "running" in d
        assert "health" in d
        assert "manager" in d
        assert "ports" in d
        assert "confidence" in d
        assert "last_checked_at" in d
        assert "backend" in d
        assert "xray_artifacts" in d


# ---------------------------------------------------------------------------
# MTProxy detection
# ---------------------------------------------------------------------------

class TestMTProxyDetection:
    def test_not_installed_no_docker_no_native(self):
        from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy.shutil.which",
                                  return_value=None):
            state = detect_mtproxy()
        assert state.installed is False
        assert state.health == ModuleHealth.not_installed

    def test_healthy_running_container(self):
        from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch(
                 "daran_proxy_stack.discovery.modules.mtproxy._docker_find_container",
                 return_value=("mtproxy", "Up 3 hours", "0.0.0.0:443->443/tcp",
                               "telegrammessenger/proxy:latest"),
             ), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._tcp_port_listening",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._detect_server_ip",
                                  return_value="1.2.3.4"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._find_generated_dir",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._read_secret",
                                  return_value="aabbccdd11223344aabbccdd11223344"):
            state = detect_mtproxy()

        assert state.installed is True
        assert state.running is True
        assert state.health == ModuleHealth.healthy
        assert state.version == "telegrammessenger/proxy:latest"
        assert state.runtime is not None
        assert state.runtime.container_running is True
        assert state.runtime.container_name == "mtproxy"
        assert len(state.ports) == 1
        assert state.ports[0].port == 443
        assert state.client_artifacts is not None
        assert state.client_artifacts.secret_present is True
        assert state.client_artifacts.tg_link is not None
        assert "tg://proxy" in state.client_artifacts.tg_link

    def test_stopped_container(self):
        from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch(
                 "daran_proxy_stack.discovery.modules.mtproxy._docker_find_container",
                 return_value=("mtproxy", "Exited (0) 1 hour ago", "",
                               "telegrammessenger/proxy:latest"),
             ), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._tcp_port_listening",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._detect_server_ip",
                                  return_value="1.2.3.4"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._find_generated_dir",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._read_secret",
                                  return_value=None):
            state = detect_mtproxy()

        assert state.installed is True
        assert state.running is False
        assert state.health == ModuleHealth.stopped

    def test_degraded_running_no_secret(self):
        from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch(
                 "daran_proxy_stack.discovery.modules.mtproxy._docker_find_container",
                 return_value=("mtproxy", "Up 1 hour", "0.0.0.0:443->443/tcp",
                               "telegrammessenger/proxy:latest"),
             ), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._tcp_port_listening",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._detect_server_ip",
                                  return_value="1.2.3.4"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._find_generated_dir",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy._read_secret",
                                  return_value=None):
            state = detect_mtproxy()

        assert state.health == ModuleHealth.degraded
        assert state.client_artifacts is not None
        assert state.client_artifacts.secret_present is False
        assert state.client_artifacts.tg_link is None

    def test_to_dict_structure(self):
        from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.mtproxy.shutil.which",
                                  return_value=None):
            state = detect_mtproxy()
        d = state.to_dict()
        assert "installed" in d
        assert "health" in d
        assert "ports" in d
        assert "client_artifacts" in d
        assert "runtime" in d
        assert "public_endpoint" in d

    def test_parse_docker_port_standard(self):
        from daran_proxy_stack.discovery.modules.mtproxy import _parse_docker_port
        bind, port = _parse_docker_port("0.0.0.0:443->443/tcp")
        assert bind == "0.0.0.0"
        assert port == 443

    def test_parse_docker_port_empty(self):
        from daran_proxy_stack.discovery.modules.mtproxy import _parse_docker_port
        bind, port = _parse_docker_port("")
        assert bind is None
        assert port is None


# ---------------------------------------------------------------------------
# Cascade detection
# ---------------------------------------------------------------------------

class TestCascadeDetection:
    def test_not_installed_no_tools(self):
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade.shutil.which",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._detect_3proxy",
                                  return_value=(False, False)):
            state = detect_cascade()
        assert state.installed is False
        assert state.health == ModuleHealth.not_installed

    def test_stopped_iptables_no_rules(self):
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade

        def _which(name):
            return "/sbin/iptables" if name == "iptables" else None

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._detect_3proxy",
                                  return_value=(False, False)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._parse_iptables_rules",
                                  return_value=[]), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._load_persisted_state",
                                  return_value=None):
            state = detect_cascade()

        assert state.installed is True
        assert state.health == ModuleHealth.stopped
        assert state.rules == []

    def test_healthy_active_iptables_rule(self):
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade

        def _which(name):
            return "/sbin/iptables" if name == "iptables" else None

        fake_rules = [{
            "protocol": "tcp",
            "listen_port": 443,
            "target_host": "10.0.0.2",
            "target_port": 8443,
            "source": "iptables",
        }]

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._detect_3proxy",
                                  return_value=(False, False)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._parse_iptables_rules",
                                  return_value=fake_rules), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._load_persisted_state",
                                  return_value=None):
            state = detect_cascade()

        assert state.installed is True
        assert state.health == ModuleHealth.healthy
        assert len(state.rules) == 1
        assert state.rules[0].listen_port == 443
        assert state.rules[0].status == "active"
        assert state.diagnostics_info is not None
        assert state.diagnostics_info.active_rule_count == 1

    def test_degraded_persisted_rule_not_in_iptables(self):
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade

        def _which(name):
            return "/sbin/iptables" if name == "iptables" else None

        persisted = {
            "relay_port": 9000,
            "upstream_socks_host": "127.0.0.1",
            "upstream_socks_port": 40000,
        }

        with unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade.shutil.which",
                                  side_effect=_which), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._detect_3proxy",
                                  return_value=(False, False)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._parse_iptables_rules",
                                  return_value=[]), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._load_persisted_state",
                                  return_value=persisted):
            state = detect_cascade()

        # persisted rule not confirmed in iptables → broken or degraded
        assert state.installed is True
        assert state.health in (ModuleHealth.broken, ModuleHealth.stopped)
        assert len(state.rules) == 1
        assert state.rules[0].status == "unknown"
        assert any("9000" in w or "not seen" in w for w in state.warnings)

    def test_to_dict_structure(self):
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade.shutil.which",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.cascade._detect_3proxy",
                                  return_value=(False, False)):
            state = detect_cascade()
        d = state.to_dict()
        assert "installed" in d
        assert "health" in d
        assert "rules" in d
        assert "rule_backend" in d
        assert "diagnostics" in d

    def test_cascade_rule_to_dict(self):
        from daran_proxy_stack.discovery.modules.cascade import CascadeRule
        r = CascadeRule(
            id="rule-001", protocol="tcp",
            listen_port=443, target_host="10.0.0.2",
            target_port=8443, status="active",
        )
        d = r.to_dict()
        assert d["listen_port"] == 443
        assert d["status"] == "active"
        assert d["target_host"] == "10.0.0.2"


# ---------------------------------------------------------------------------
# 3x-ui detection
# ---------------------------------------------------------------------------

class TestXuiDetection:
    def test_not_installed_no_binary_no_unit(self):
        from daran_proxy_stack.discovery.modules.xui import detect_xui
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_binary",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_systemd",
                                  return_value=(False, False)):
            state = detect_xui()
        assert state.installed is False
        assert state.health == ModuleHealth.not_installed
        assert state.confidence == DiscoveryConfidence.full
        assert state.running is False
        assert state.binary_path is None

    def test_healthy_systemd_active_web_up(self):
        from daran_proxy_stack.discovery.modules.xui import detect_xui
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_binary",
                                  return_value="/usr/local/x-ui/x-ui"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_systemd",
                                  return_value=(True, True)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_service_enabled",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_process",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._probe_web_ui",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_version",
                                  return_value="2.3.11"):
            state = detect_xui()
        assert state.installed is True
        assert state.running is True
        assert state.enabled is True
        assert state.health == ModuleHealth.healthy
        assert state.web_ui_responding is True
        assert state.version == "2.3.11"
        assert state.binary_path == "/usr/local/x-ui/x-ui"
        assert len(state.ports) == 1
        assert state.ports[0].port == 2053
        assert state.ports[0].purpose == "web-ui"

    def test_stopped_unit_exists_but_not_active_no_web(self):
        from daran_proxy_stack.discovery.modules.xui import detect_xui
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_binary",
                                  return_value="/usr/local/x-ui/x-ui"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_systemd",
                                  return_value=(True, False)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_service_enabled",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_process",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._probe_web_ui",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_version",
                                  return_value=None):
            state = detect_xui()
        assert state.installed is True
        assert state.running is False
        assert state.health == ModuleHealth.stopped
        assert state.web_ui_responding is False
        assert len(state.ports) == 0

    def test_degraded_running_but_web_not_responding(self):
        from daran_proxy_stack.discovery.modules.xui import detect_xui
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_binary",
                                  return_value="/usr/local/x-ui/x-ui"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_systemd",
                                  return_value=(True, True)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_service_enabled",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_process",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._probe_web_ui",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_version",
                                  return_value=None):
            state = detect_xui()
        assert state.installed is True
        assert state.running is True
        assert state.health == ModuleHealth.degraded
        assert any("web UI" in w for w in state.warnings)

    def test_process_only_no_systemd_healthy(self):
        from daran_proxy_stack.discovery.modules.xui import detect_xui
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_binary",
                                  return_value="/usr/local/x-ui/x-ui"), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_systemd",
                                  return_value=(False, False)), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_service_enabled",
                                  return_value=False), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_process",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._probe_web_ui",
                                  return_value=True), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_version",
                                  return_value=None):
            state = detect_xui()
        assert state.installed is True
        assert state.running is True
        assert state.health == ModuleHealth.healthy
        assert state.manager == ModuleManager.process

    def test_to_dict_structure(self):
        from daran_proxy_stack.discovery.modules.xui import detect_xui
        with unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_binary",
                                  return_value=None), \
             unittest.mock.patch("daran_proxy_stack.discovery.modules.xui._detect_xui_systemd",
                                  return_value=(False, False)):
            state = detect_xui()
        d = state.to_dict()
        assert "installed" in d
        assert "running" in d
        assert "health" in d
        assert "manager" in d
        assert "ports" in d
        assert "confidence" in d
        assert "last_checked_at" in d
        assert "binary_path" in d
        assert "web_ui_responding" in d
        assert "web_ui_port" in d


# ---------------------------------------------------------------------------
# Runner (ObservedState assembly)
# ---------------------------------------------------------------------------

class TestRunner:
    def _make_not_installed_state(self, module_cls):
        """Create a minimal not_installed state for a module."""
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        now = datetime.now(timezone.utc).isoformat()
        return module_cls(
            installed=False, enabled=False, running=False,
            health=ModuleHealth.not_installed,
            version=None, manager=ModuleManager.none,
            last_checked_at=now,
        )

    def test_run_discovery_returns_observed_state(self):
        from daran_proxy_stack.discovery.runner import run_discovery
        from daran_proxy_stack.discovery.schema import HostState
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from daran_proxy_stack.discovery.modules.mtproxy import MTProxyState
        from daran_proxy_stack.discovery.modules.cascade import CascadeState
        from daran_proxy_stack.discovery.modules.xui import XuiState

        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        now = datetime.now(timezone.utc).isoformat()

        fake_warp = WarpState(installed=False, enabled=False, running=False,
                              health=ModuleHealth.not_installed, version=None,
                              manager=ModuleManager.none, last_checked_at=now)
        fake_mtp = MTProxyState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_cas = CascadeState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_xui = XuiState(installed=False, enabled=False, running=False,
                            health=ModuleHealth.not_installed, version=None,
                            manager=ModuleManager.none, last_checked_at=now)
        fake_host = HostState(os="ubuntu", version="24.04",
                              public_ip="1.2.3.4", hostname="node-1")

        with unittest.mock.patch("daran_proxy_stack.discovery.runner.discover_host", return_value=fake_host), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_warp", return_value=fake_warp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_mtproxy", return_value=fake_mtp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_cascade", return_value=fake_cas), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_xui", return_value=fake_xui):
            state = run_discovery()

        assert isinstance(state, ObservedState)
        assert state.schema_version == "1.0"
        assert state.host.os == "ubuntu"
        assert state.warp is not None
        assert state.mtproxy is not None
        assert state.cascade is not None
        assert state.xui is not None

    def test_discovery_dict_is_serialisable(self):
        import json
        from daran_proxy_stack.discovery.runner import discovery_dict
        from daran_proxy_stack.discovery.schema import HostState, ModuleHealth, ModuleManager
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from daran_proxy_stack.discovery.modules.mtproxy import MTProxyState
        from daran_proxy_stack.discovery.modules.cascade import CascadeState
        from daran_proxy_stack.discovery.modules.xui import XuiState

        now = datetime.now(timezone.utc).isoformat()
        fake_warp = WarpState(installed=False, enabled=False, running=False,
                              health=ModuleHealth.not_installed, version=None,
                              manager=ModuleManager.none, last_checked_at=now)
        fake_mtp = MTProxyState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_cas = CascadeState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_xui = XuiState(installed=False, enabled=False, running=False,
                            health=ModuleHealth.not_installed, version=None,
                            manager=ModuleManager.none, last_checked_at=now)
        fake_host = HostState(os="ubuntu", version="24.04",
                              public_ip="1.2.3.4", hostname="node-1")

        with unittest.mock.patch("daran_proxy_stack.discovery.runner.discover_host", return_value=fake_host), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_warp", return_value=fake_warp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_mtproxy", return_value=fake_mtp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_cascade", return_value=fake_cas), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_xui", return_value=fake_xui):
            d = discovery_dict()

        # Must be JSON-serialisable
        serialised = json.dumps(d)
        assert len(serialised) > 0
        parsed = json.loads(serialised)
        assert parsed["schema_version"] == "1.0"
        assert "host" in parsed
        assert "discovery" in parsed
        assert "modules" in parsed
        assert "warp" in parsed["modules"]
        assert "mtproxy" in parsed["modules"]
        assert "cascade" in parsed["modules"]
        assert "xui" in parsed["modules"]

    def test_run_discovery_tolerates_warp_detector_crash(self):
        from daran_proxy_stack.discovery.runner import run_discovery
        from daran_proxy_stack.discovery.schema import HostState, ModuleHealth
        from daran_proxy_stack.discovery.modules.mtproxy import MTProxyState
        from daran_proxy_stack.discovery.modules.cascade import CascadeState
        from daran_proxy_stack.discovery.modules.xui import XuiState
        from daran_proxy_stack.discovery.schema import ModuleManager

        now = datetime.now(timezone.utc).isoformat()
        fake_mtp = MTProxyState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_cas = CascadeState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_xui = XuiState(installed=False, enabled=False, running=False,
                            health=ModuleHealth.not_installed, version=None,
                            manager=ModuleManager.none, last_checked_at=now)
        fake_host = HostState(os="ubuntu", version="24.04",
                              public_ip="1.2.3.4", hostname="node-1")

        with unittest.mock.patch("daran_proxy_stack.discovery.runner.discover_host", return_value=fake_host), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_warp",
                                  side_effect=RuntimeError("warp detector kaboom")), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_mtproxy", return_value=fake_mtp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_cascade", return_value=fake_cas), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_xui", return_value=fake_xui):
            state = run_discovery()

        assert state.warp is not None  # fallback created, not None
        assert state.warp.health == ModuleHealth.unknown
        assert "warp" in state.discovery.partial_modules
        assert state.discovery.status == "partial"

    def test_discovery_meta_ok_when_all_full_confidence(self):
        from daran_proxy_stack.discovery.runner import run_discovery
        from daran_proxy_stack.discovery.schema import HostState, ModuleHealth, ModuleManager
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from daran_proxy_stack.discovery.modules.mtproxy import MTProxyState
        from daran_proxy_stack.discovery.modules.cascade import CascadeState
        from daran_proxy_stack.discovery.modules.xui import XuiState

        now = datetime.now(timezone.utc).isoformat()
        fake_warp = WarpState(installed=False, enabled=False, running=False,
                              health=ModuleHealth.not_installed, version=None,
                              manager=ModuleManager.none, last_checked_at=now,
                              confidence=DiscoveryConfidence.full)
        fake_mtp = MTProxyState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now,
                                confidence=DiscoveryConfidence.full)
        fake_cas = CascadeState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now,
                                confidence=DiscoveryConfidence.full)
        fake_xui = XuiState(installed=False, enabled=False, running=False,
                            health=ModuleHealth.not_installed, version=None,
                            manager=ModuleManager.none, last_checked_at=now,
                            confidence=DiscoveryConfidence.full)
        fake_host = HostState(os="ubuntu", version="24.04",
                              public_ip="1.2.3.4", hostname="node-1")

        with unittest.mock.patch("daran_proxy_stack.discovery.runner.discover_host", return_value=fake_host), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_warp", return_value=fake_warp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_mtproxy", return_value=fake_mtp), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_cascade", return_value=fake_cas), \
             unittest.mock.patch("daran_proxy_stack.discovery.runner.detect_xui", return_value=fake_xui):
            state = run_discovery()

        assert state.discovery.status == "ok"
        assert state.discovery.partial_modules == []


# ===========================================================================
# Compat adapter tests
# ===========================================================================

class TestCompatAdapter:
    """Tests for discovery/compat.py — ObservedState → legacy inventory schema."""

    def _make_observed_state(self):
        """Build a minimal ObservedState with all modules not_installed."""
        import unittest.mock
        from datetime import datetime, timezone
        from daran_proxy_stack.discovery.schema import (
            HostState, DiscoveryMeta, ObservedState, ModuleHealth, ModuleManager
        )
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from daran_proxy_stack.discovery.modules.mtproxy import MTProxyState
        from daran_proxy_stack.discovery.modules.cascade import CascadeState

        from daran_proxy_stack.discovery.modules.xui import XuiState

        now = datetime.now(timezone.utc).isoformat()
        fake_warp = WarpState(installed=False, enabled=False, running=False,
                              health=ModuleHealth.not_installed, version=None,
                              manager=ModuleManager.none, last_checked_at=now)
        fake_mtp = MTProxyState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_cas = CascadeState(installed=False, enabled=False, running=False,
                                health=ModuleHealth.not_installed, version=None,
                                manager=ModuleManager.none, last_checked_at=now)
        fake_xui = XuiState(installed=False, enabled=False, running=False,
                            health=ModuleHealth.not_installed, version=None,
                            manager=ModuleManager.none, last_checked_at=now)
        host = HostState(os="ubuntu", version="24.04", public_ip="1.2.3.4", hostname="node-1")
        meta = DiscoveryMeta(last_run_at=now, status="ok")
        return ObservedState(schema_version="1.0", host=host, discovery=meta,
                             warp=fake_warp, mtproxy=fake_mtp, cascade=fake_cas,
                             xui=fake_xui)

    def test_inventory_dict_top_level_keys(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        d = observed_state_to_inventory_dict(state)
        for key in ("services", "timestamp", "count", "detected_count", "running_count"):
            assert key in d, f"missing key: {key}"

    def test_inventory_dict_service_count(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        d = observed_state_to_inventory_dict(state)
        assert d["count"] == 4
        assert len(d["services"]) == 4

    def test_inventory_dict_service_names(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        d = observed_state_to_inventory_dict(state)
        names = {s["name"] for s in d["services"]}
        assert names == {"warp", "mtproxy", "cascade", "xui"}

    def test_inventory_dict_service_fields(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        d = observed_state_to_inventory_dict(state)
        required = {"name", "label", "detected", "version", "runtime_status",
                    "config_path", "endpoint", "meta"}
        for svc in d["services"]:
            assert required.issubset(svc.keys()), f"missing fields in {svc['name']}"

    def test_not_installed_maps_to_correct_status(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        d = observed_state_to_inventory_dict(state)
        for svc in d["services"]:
            assert svc["runtime_status"] == "not_installed"
            assert svc["detected"] is False

    def test_healthy_module_maps_to_running(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from datetime import datetime, timezone

        state = self._make_observed_state()
        now = datetime.now(timezone.utc).isoformat()
        state.warp = WarpState(installed=True, enabled=True, running=True,
                               health=ModuleHealth.healthy, version="2024.1.0",
                               manager=ModuleManager.systemd, last_checked_at=now)
        d = observed_state_to_inventory_dict(state)
        warp_svc = next(s for s in d["services"] if s["name"] == "warp")
        assert warp_svc["runtime_status"] == "running"
        assert warp_svc["detected"] is True
        assert warp_svc["version"] == "2024.1.0"

    def test_degraded_module_maps_to_running(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from datetime import datetime, timezone

        state = self._make_observed_state()
        now = datetime.now(timezone.utc).isoformat()
        state.warp = WarpState(installed=True, enabled=True, running=True,
                               health=ModuleHealth.degraded, version=None,
                               manager=ModuleManager.systemd, last_checked_at=now)
        d = observed_state_to_inventory_dict(state)
        warp_svc = next(s for s in d["services"] if s["name"] == "warp")
        assert warp_svc["runtime_status"] == "running"

    def test_broken_module_maps_to_unknown(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from datetime import datetime, timezone

        state = self._make_observed_state()
        now = datetime.now(timezone.utc).isoformat()
        state.warp = WarpState(installed=True, enabled=False, running=False,
                               health=ModuleHealth.broken, version=None,
                               manager=ModuleManager.systemd, last_checked_at=now)
        d = observed_state_to_inventory_dict(state)
        warp_svc = next(s for s in d["services"] if s["name"] == "warp")
        assert warp_svc["runtime_status"] == "unknown"

    def test_none_module_slot_handled_gracefully(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        state.warp = None
        d = observed_state_to_inventory_dict(state)
        warp_svc = next(s for s in d["services"] if s["name"] == "warp")
        assert warp_svc["runtime_status"] == "unknown"
        assert warp_svc["detected"] is False

    def test_backend_marker_present(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        state = self._make_observed_state()
        d = observed_state_to_inventory_dict(state)
        assert d.get("_backend") == "discovery/v1"

    def test_detected_and_running_counts(self):
        from daran_proxy_stack.discovery.compat import observed_state_to_inventory_dict
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from datetime import datetime, timezone

        state = self._make_observed_state()
        now = datetime.now(timezone.utc).isoformat()
        state.warp = WarpState(installed=True, enabled=True, running=True,
                               health=ModuleHealth.healthy, version=None,
                               manager=ModuleManager.systemd, last_checked_at=now)
        d = observed_state_to_inventory_dict(state)
        assert d["detected_count"] == 1
        assert d["running_count"] == 1

    def test_inventory_dict_from_discovery_uses_new_backend(self):
        """inventory_dict_from_discovery() should call run_discovery(), not legacy path."""
        import unittest.mock
        from daran_proxy_stack.discovery.compat import inventory_dict_from_discovery
        state = self._make_observed_state()
        with unittest.mock.patch(
            "daran_proxy_stack.discovery.runner.run_discovery", return_value=state
        ) as mock_run:
            d = inventory_dict_from_discovery()
        mock_run.assert_called_once()
        assert d.get("_backend") == "discovery/v1"
        assert "services" in d
