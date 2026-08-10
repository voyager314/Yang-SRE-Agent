from __future__ import annotations

from unittest.mock import MagicMock

from sre_agent.config import Config
from sre_agent.core.engine import Engine
from sre_agent.core.llm import DefaultLLM, ModelResponse
from sre_agent.core.tool import (
    CommandPrerequisite,
    StructuredToolResult,
    Tool,
    ToolResultStatus,
    Toolset,
    YAMLTool,
)
from sre_agent.core.tool_executor import ToolExecutor
from sre_agent.core.toolset_manager import ToolsetManager
from sre_agent.utils.jinja import extract_variables, render_template


class TestConfig:
    def test_default_config_loads(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("model: gpt-4.1\nmax_steps: 10\n")
        config = Config(_config_file=str(config_file))
        assert config.model == "gpt-4.1"
        assert config.max_steps == 10

    def test_resolve_model_from_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("model: gpt-4.1\n")
        config = Config(_config_file=str(config_file))
        entry = config.resolve_model()
        assert entry.model == "gpt-4.1"

    def test_resolve_model_cli_override(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("model: gpt-4.1\n")
        config = Config(_config_file=str(config_file))
        entry = config.resolve_model("claude-sonnet")
        assert entry.model == "claude-sonnet"


class TestJinja:
    def test_render_template(self):
        result = render_template("hello {{ name }}", {"name": "world"})
        assert result == "hello world"

    def test_extract_variables_required(self):
        vars = extract_variables("kubectl get {{ kind }} -n {{ namespace }}")
        names = [v[0] for v in vars]
        assert "kind" in names
        assert "namespace" in names
        assert all(not has_default for _, has_default in vars)

    def test_extract_variables_with_default(self):
        vars = extract_variables("--tail={{ lines | default(100) }}")
        assert ("lines", True) in vars


class TestToolSystem:
    def test_structured_tool_result(self):
        r = StructuredToolResult(status=ToolResultStatus.SUCCESS, data="hello")
        assert r.status == ToolResultStatus.SUCCESS

    def test_tool_invoke_truncation(self):
        class BigTool(Tool):
            def _invoke(self, params):
                return StructuredToolResult(
                    status=ToolResultStatus.SUCCESS,
                    data="\n".join(f"line {i}" for i in range(5000)),
                )

        tool = BigTool(name="big", description="big output")
        result = tool.invoke({}, max_output_lines=100)
        assert "截断" in str(result.data)

    def test_yaml_tool_param_inference(self):
        tool = YAMLTool(
            name="test",
            description="test",
            command="kubectl get {{ kind }} -n {{ namespace }}",
            render_func=render_template,
        )
        props = tool.parameters["properties"]
        assert "kind" in props
        assert "namespace" in props


class TestToolExecutor:
    def test_register_and_execute(self):
        class EchoTool(Tool):
            def _invoke(self, params):
                return StructuredToolResult(
                    status=ToolResultStatus.SUCCESS,
                    data=params.get("msg", ""),
                )

        executor = ToolExecutor()
        executor.register(EchoTool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        ))
        result = executor.execute("echo", {"msg": "hi"})
        assert result.status == ToolResultStatus.SUCCESS
        assert result.data == "hi"

    def test_unknown_tool(self):
        executor = ToolExecutor()
        result = executor.execute("nonexistent", {})
        assert result.status == ToolResultStatus.ERROR


class TestEngine:
    def test_call_no_tools(self):
        mock_llm = MagicMock(spec=DefaultLLM)
        mock_llm.completion.return_value = ModelResponse(
            content="The pod crashed due to OOM.",
            tool_calls=[],
        )

        executor = ToolExecutor()
        engine = Engine(llm=mock_llm, tool_executor=executor)
        result = engine.call([
            {"role": "system", "content": "You are an SRE."},
            {"role": "user", "content": "Why did the pod crash?"},
        ])
        assert result.answer == "The pod crashed due to OOM."
        assert result.iterations == 1

    def test_call_with_tool_use(self):
        mock_llm = MagicMock(spec=DefaultLLM)
        mock_llm.completion.side_effect = [
            ModelResponse(
                content=None,
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"msg": "hello"}'},
                }],
            ),
            ModelResponse(
                content="Based on the echo result: hello",
                tool_calls=[],
            ),
        ]

        class EchoTool(Tool):
            def _invoke(self, params):
                return StructuredToolResult(
                    status=ToolResultStatus.SUCCESS, data=params.get("msg", "")
                )

        executor = ToolExecutor()
        executor.register(EchoTool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        ))

        engine = Engine(llm=mock_llm, tool_executor=executor)
        result = engine.call([{"role": "user", "content": "test"}])
        assert "hello" in result.answer
        assert result.iterations == 2

    def test_max_steps_reached(self):
        mock_llm = MagicMock(spec=DefaultLLM)
        mock_llm.completion.return_value = ModelResponse(
            content=None,
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"msg": "loop"}'},
            }],
        )

        class EchoTool(Tool):
            def _invoke(self, params):
                return StructuredToolResult(status=ToolResultStatus.SUCCESS, data="loop")

        executor = ToolExecutor()
        executor.register(EchoTool(
            name="echo", description="echo",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        ))

        engine = Engine(llm=mock_llm, tool_executor=executor, max_steps=3)
        result = engine.call([{"role": "user", "content": "test"}])
        assert "最大步数" in result.answer


class TestToolsetManager:
    def test_prerequisite_failure_graceful(self):

        class FailTool(Tool):
            def _invoke(self, params):
                return StructuredToolResult(status=ToolResultStatus.SUCCESS, data="ok")

        ts = Toolset(
            name="failing",
            tools=[FailTool(name="fail", description="fail")],
            prerequisites=[CommandPrerequisite("nonexistent_command_xyz")],
        )
        mgr = ToolsetManager()
        mgr._toolsets = [ts]
        mgr.check_prerequisites()
        assert mgr.get_available_toolsets() == []


class TestMultiTurnConversation:
    def test_context_preserved_across_turns(self):
        mock_llm = MagicMock(spec=DefaultLLM)
        mock_llm.completion.side_effect = [
            ModelResponse(content="The pod is in CrashLoopBackOff.", tool_calls=[]),
            ModelResponse(content="It crashed due to OOM, as I mentioned.", tool_calls=[]),
        ]

        executor = ToolExecutor()
        engine = Engine(llm=mock_llm, tool_executor=executor)

        messages = [
            {"role": "system", "content": "You are an SRE."},
            {"role": "user", "content": "What is the pod status?"},
        ]
        result1 = engine.call(messages)
        assert "CrashLoopBackOff" in result1.answer

        messages.append({"role": "assistant", "content": result1.answer})
        messages.append({"role": "user", "content": "Why did it crash?"})
        result2 = engine.call(messages)
        assert "OOM" in result2.answer

        second_call_messages = mock_llm.completion.call_args_list[1][0][0]
        assert len(second_call_messages) == 4
        assert second_call_messages[2]["role"] == "assistant"
        assert "CrashLoopBackOff" in second_call_messages[2]["content"]


class TestScratchpad:
    def test_initial_state_empty(self):
        from sre_agent.core.scratchpad import Scratchpad
        sp = Scratchpad()
        assert sp.is_empty()
        assert sp.findings == []
        assert sp.hypotheses == []
        assert sp.ruled_out == []
        assert sp.next_steps == []

    def test_update_full_replace(self):
        from sre_agent.core.scratchpad import Scratchpad
        sp = Scratchpad(findings=["old finding"])
        sp.update(findings=["new finding"], hypotheses=["h1"])
        assert sp.findings == ["new finding"]
        assert sp.hypotheses == ["h1"]
        assert sp.ruled_out == []

    def test_update_partial_preserves_unchanged_fields(self):
        from sre_agent.core.scratchpad import Scratchpad
        sp = Scratchpad(findings=["f1"], hypotheses=["h1"])
        sp.update(ruled_out=["r1"])
        assert sp.findings == ["f1"]
        assert sp.hypotheses == ["h1"]
        assert sp.ruled_out == ["r1"]

    def test_is_empty_after_partial_update(self):
        from sre_agent.core.scratchpad import Scratchpad
        sp = Scratchpad()
        sp.update(findings=["cpu spike"])
        assert not sp.is_empty()

    def test_to_yaml_contains_all_fields(self):
        from sre_agent.core.scratchpad import Scratchpad
        sp = Scratchpad(findings=["f1"], hypotheses=["h1"], ruled_out=["r1"], next_steps=["n1"])
        out = sp.to_yaml()
        assert "findings" in out
        assert "hypotheses" in out
        assert "ruled_out" in out
        assert "next_steps" in out
        assert "f1" in out

    def test_to_yaml_empty_scratchpad(self):
        from sre_agent.core.scratchpad import Scratchpad
        sp = Scratchpad()
        out = sp.to_yaml()
        assert "findings" in out
        assert "[]" in out


class TestEvidenceStore:
    def test_save_and_load_roundtrip(self, tmp_path):
        from sre_agent.core.evidence_store import EvidenceStore
        store = EvidenceStore(base_dir=tmp_path)
        store.save("call_abc", "full output content")
        result = store.load("call_abc")
        assert result == "full output content"

    def test_load_missing_returns_none(self, tmp_path):
        from sre_agent.core.evidence_store import EvidenceStore
        store = EvidenceStore(base_dir=tmp_path)
        assert store.load("nonexistent_id") is None

    def test_save_creates_base_dir(self, tmp_path):
        from sre_agent.core.evidence_store import EvidenceStore
        nested = tmp_path / "a" / "b" / "c"
        store = EvidenceStore(base_dir=nested)
        store.save("call_1", "data")
        assert (nested / "call_1").exists()

    def test_save_returns_path(self, tmp_path):
        from sre_agent.core.evidence_store import EvidenceStore
        store = EvidenceStore(base_dir=tmp_path)
        path = store.save("call_xyz", "content")
        assert path == tmp_path / "call_xyz"


class TestToolsetCompress:
    def _make_long_output(self, n: int, prefix: str = "line") -> str:
        return "\n".join(f"{prefix} {i}" for i in range(n))

    def test_toolset_default_compress_short_passthrough(self):
        from sre_agent.core.tool import Toolset
        ts = Toolset(name="t", tools=[])
        short = self._make_long_output(30)
        assert ts.compress("t", short) == short

    def test_toolset_default_compress_long_folds_middle(self):
        from sre_agent.core.tool import Toolset
        ts = Toolset(name="t", tools=[])
        out = ts.compress("t", self._make_long_output(100))
        assert "折叠" in out
        assert "line 0" in out
        assert "line 99" in out

    def test_bash_compress_short_passthrough(self):
        from sre_agent.toolsets.bash import create_bash_toolset
        ts = create_bash_toolset({})
        short = self._make_long_output(30)
        assert ts.compress("bash", short) == short

    def test_bash_compress_highlights_error_lines(self):
        from sre_agent.toolsets.bash import create_bash_toolset
        ts = create_bash_toolset({})
        lines = [f"line {i}" for i in range(100)]
        lines[10] = "ERROR: something went wrong"
        lines[50] = "fatal: disk full"
        out = ts.compress("bash", "\n".join(lines))
        assert "ERROR: something went wrong" in out
        assert "fatal: disk full" in out
        assert "共 100 行" in out

    def test_bash_compress_no_errors_keeps_tail(self):
        from sre_agent.toolsets.bash import create_bash_toolset
        ts = create_bash_toolset({})
        lines = [f"line {i}" for i in range(100)]
        out = ts.compress("bash", "\n".join(lines))
        assert "line 99" in out

    def test_prometheus_compress_short_passthrough(self):
        from sre_agent.toolsets.prometheus import create_prometheus_toolset
        ts = create_prometheus_toolset({"url": "http://localhost:9090"})
        short = self._make_long_output(40)
        assert ts.compress("prometheus_query", short) == short

    def test_prometheus_compress_folds_time_points(self):
        from sre_agent.toolsets.prometheus import create_prometheus_toolset
        ts = create_prometheus_toolset({"url": "http://localhost:9090"})
        lines = ['{job="api"}:']
        lines += [f"  [ts{i}] {i * 0.1:.2f}" for i in range(100)]
        out = ts.compress("prometheus_query_range", "\n".join(lines))
        assert "折叠" in out

    def test_logs_compress_short_passthrough(self):
        import os
        os.environ["LOKI_URL"] = "http://localhost:3100"
        from sre_agent.toolsets.logs import create_logs_toolset
        ts = create_logs_toolset({"url": "http://localhost:3100"})
        short = self._make_long_output(40)
        assert ts.compress("loki_query", short) == short

    def test_logs_compress_surfaces_error_lines(self):
        import os
        os.environ["LOKI_URL"] = "http://localhost:3100"
        from sre_agent.toolsets.logs import create_logs_toolset
        ts = create_logs_toolset({"url": "http://localhost:3100"})
        lines = [f"[ts] info line {i}" for i in range(80)]
        lines[5] = "[ts] ERROR: null pointer"
        lines[40] = "[ts] WARN: slow query 3200ms"
        out = ts.compress("loki_query", "\n".join(lines))
        assert "ERROR: null pointer" in out
        assert "WARN: slow query" in out
        assert "共 80 行" in out
