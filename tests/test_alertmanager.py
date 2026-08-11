from __future__ import annotations

import pytest

from sre_agent.toolsets.alertmanager import (
    _format_alerts,
    _format_silences,
    _compress_alerts,
    AlertmanagerListTool,
    AlertmanagerSilencesTool,
    create_alertmanager_toolset,
)
from sre_agent.core.tool import ToolResultStatus


def _make_alert(alertname="TestAlert", severity="warning", namespace="default",
                pod="", message="something went wrong"):
    alert = {
        "labels": {"alertname": alertname, "severity": severity, "namespace": namespace},
        "annotations": {"message": message},
    }
    if pod:
        alert["labels"]["pod"] = pod
    return alert


def _make_silence(matcher_name="alertname", matcher_value="TestAlert",
                  created_by="admin", comment="maintenance", state="active"):
    return {
        "id": "abcd1234-5678-90ab-cdef",
        "matchers": [{"name": matcher_name, "value": matcher_value, "isRegex": False, "isEqual": True}],
        "createdBy": created_by,
        "endsAt": "2026-08-12T00:00:00Z",
        "comment": comment,
        "status": {"state": state},
    }


class TestAlertFormatting:
    def test_group_by_severity(self):
        alerts = [
            _make_alert("LowDisk", "warning"),
            _make_alert("PodCrash", "critical"),
            _make_alert("HighLatency", "info"),
            _make_alert("OOMKill", "critical"),
        ]
        result = _format_alerts(alerts)
        crit_pos = result.find("[CRITICAL]")
        warn_pos = result.find("[WARNING]")
        info_pos = result.find("[INFO]")
        assert crit_pos < warn_pos < info_pos

    def test_critical_count(self):
        alerts = [
            _make_alert("A", "critical"),
            _make_alert("B", "critical"),
            _make_alert("C", "warning"),
        ]
        result = _format_alerts(alerts)
        assert "2 alerts" in result

    def test_core_labels_shown(self):
        alerts = [_make_alert("DiskFull", "warning", "prod", "api-pod-1", "disk 95%")]
        result = _format_alerts(alerts)
        assert "DiskFull" in result
        assert "ns=prod" in result
        assert "pod=api-pod-1" in result
        assert "disk 95%" in result

    def test_no_pod_no_pod_label(self):
        alerts = [_make_alert("NoPod", "info", "staging")]
        result = _format_alerts(alerts)
        assert "NoPod" in result
        assert "pod=" not in result

    def test_empty_alerts(self):
        result = _format_alerts([])
        assert result.strip() == ""

    def test_unknown_severity(self):
        alerts = [_make_alert("Custom", "page")]
        result = _format_alerts(alerts)
        assert "[PAGE]" in result


class TestSilenceFormatting:
    def test_basic_silence(self):
        silences = [_make_silence("alertname", "HighCPU", "oncall", "planned work")]
        result = _format_silences(silences)
        assert "alertname=HighCPU" in result
        assert "by=oncall" in result
        assert "planned work" in result

    def test_regex_matcher(self):
        s = _make_silence()
        s["matchers"] = [{"name": "namespace", "value": "test.*", "isRegex": True, "isEqual": True}]
        result = _format_silences([s])
        assert "namespace=~test.*" in result

    def test_negative_matcher(self):
        s = _make_silence()
        s["matchers"] = [{"name": "env", "value": "prod", "isRegex": False, "isEqual": False}]
        result = _format_silences([s])
        assert "env!=prod" in result

    def test_multiple_matchers(self):
        s = _make_silence()
        s["matchers"] = [
            {"name": "alertname", "value": "A", "isRegex": False, "isEqual": True},
            {"name": "namespace", "value": "B", "isRegex": False, "isEqual": True},
        ]
        result = _format_silences([s])
        assert "alertname=A" in result
        assert "namespace=B" in result


class TestCompressLogic:
    def test_short_output_not_compressed(self):
        output = "\n".join([f"line {i}" for i in range(30)])
        assert _compress_alerts(output) == output

    def test_exactly_50_lines_not_compressed(self):
        output = "\n".join([f"line {i}" for i in range(50)])
        assert _compress_alerts(output) == output

    def test_large_output_compressed(self):
        lines = ["[CRITICAL] (60 alerts)", "-" * 40]
        for i in range(60):
            lines.append(f"  HighCPU | ns=prod | pod=api-{i}")
            lines.append(f"    CPU usage at 95% on pod api-{i}")
        output = "\n".join(lines)
        compressed = _compress_alerts(output)
        assert "Compressed" in compressed
        assert "x60" in compressed

    def test_multiple_alertnames_compressed(self):
        lines = ["[WARNING] (55 alerts)", "-" * 40]
        for i in range(30):
            lines.append(f"  HighCPU | ns=prod")
            lines.append(f"    cpu high")
        for i in range(25):
            lines.append(f"  LowDisk | ns=prod")
            lines.append(f"    disk low")
        output = "\n".join(lines)
        compressed = _compress_alerts(output)
        assert "HighCPU" in compressed
        assert "LowDisk" in compressed
        assert "x30" in compressed
        assert "x25" in compressed


class TestAlertmanagerFactory:
    def test_no_url_returns_unconfigured(self, monkeypatch):
        monkeypatch.delenv("ALERTMANAGER_URL", raising=False)
        toolset = create_alertmanager_toolset({})
        assert toolset.name == "alertmanager"
        assert len(toolset.tools) == 0

    def test_url_from_config(self):
        toolset = create_alertmanager_toolset({"url": "http://alertmanager:9093"})
        assert len(toolset.tools) == 2
        names = [t.name for t in toolset.tools]
        assert "alertmanager_list" in names
        assert "alertmanager_silences" in names

    def test_url_from_env(self, monkeypatch):
        monkeypatch.setenv("ALERTMANAGER_URL", "http://am:9093")
        toolset = create_alertmanager_toolset({})
        assert len(toolset.tools) == 2

    def test_only_two_tools_registered(self):
        toolset = create_alertmanager_toolset({"url": "http://am:9093"})
        assert len(toolset.tools) == 2

    def test_compress_short_passthrough(self):
        toolset = create_alertmanager_toolset({"url": "http://am:9093"})
        short = "just a few lines\nof output"
        assert toolset.compress("alertmanager_list", short) == short

    def test_compress_silences_passthrough(self):
        toolset = create_alertmanager_toolset({"url": "http://am:9093"})
        long_output = "\n".join([f"line{i}" for i in range(100)])
        assert toolset.compress("alertmanager_silences", long_output) == long_output
