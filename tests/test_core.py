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
        executor.register(
            EchoTool(
                name="echo",
                description="echo",
                parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
            )
        )
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
        result = engine.call(
            [
                {"role": "system", "content": "You are an SRE."},
                {"role": "user", "content": "Why did the pod crash?"},
            ]
        )
        assert result.answer == "The pod crashed due to OOM."
        assert result.iterations == 1

    def test_call_with_tool_use(self):
        mock_llm = MagicMock(spec=DefaultLLM)
        mock_llm.completion.side_effect = [
            ModelResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"msg": "hello"}'},
                    }
                ],
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
        executor.register(
            EchoTool(
                name="echo",
                description="echo",
                parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
            )
        )

        engine = Engine(llm=mock_llm, tool_executor=executor)
        result = engine.call([{"role": "user", "content": "test"}])
        assert "hello" in result.answer
        assert result.iterations == 2

    def test_max_steps_reached(self):
        mock_llm = MagicMock(spec=DefaultLLM)
        mock_llm.completion.return_value = ModelResponse(
            content=None,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"msg": "loop"}'},
                }
            ],
        )

        class EchoTool(Tool):
            def _invoke(self, params):
                return StructuredToolResult(status=ToolResultStatus.SUCCESS, data="loop")

        executor = ToolExecutor()
        executor.register(
            EchoTool(
                name="echo",
                description="echo",
                parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
            )
        )

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


class TestContextManager:
    def _make_llm(self, used_tokens: int, window: int):
        from sre_agent.core.llm import LLM, ModelResponse

        class FakeLLM(LLM):
            def completion(self, messages, tools=None, tool_choice=None):
                return ModelResponse()

            def count_tokens(self, messages, tools=None):
                return used_tokens

            def get_context_window_size(self):
                return window

        return FakeLLM()

    def _make_cm(self, used: int, window: int, tmp_path=None):
        from pathlib import Path

        from sre_agent.core.context_manager import ContextManager
        from sre_agent.core.evidence_store import EvidenceStore
        from sre_agent.core.scratchpad import Scratchpad

        base = tmp_path or Path("/tmp/test_cm")
        return ContextManager(
            llm=self._make_llm(used, window),
            evidence_store=EvidenceStore(base_dir=base),
            scratchpad=Scratchpad(),
            toolsets={},
        )

    def test_check_budget_normal(self, tmp_path):
        from sre_agent.core.context_manager import BudgetStatus

        cm = self._make_cm(used=6000, window=100_000, tmp_path=tmp_path)
        assert cm.check_budget([]) == BudgetStatus.NORMAL

    def test_check_budget_compress(self, tmp_path):
        from sre_agent.core.context_manager import BudgetStatus

        cm = self._make_cm(used=75_000, window=100_000, tmp_path=tmp_path)
        assert cm.check_budget([]) == BudgetStatus.COMPRESS

    def test_check_budget_converge(self, tmp_path):
        from sre_agent.core.context_manager import BudgetStatus

        cm = self._make_cm(used=91_000, window=100_000, tmp_path=tmp_path)
        assert cm.check_budget([]) == BudgetStatus.CONVERGE

    def test_compress_immediate_short_passthrough(self, tmp_path):
        cm = self._make_cm(used=0, window=100_000, tmp_path=tmp_path)
        short = "x" * 100
        assert cm.compress_immediate("c1", "bash", short) == short

    def test_compress_immediate_long_stores_and_compresses(self, tmp_path):
        from sre_agent.core.evidence_store import EvidenceStore

        cm = self._make_cm(used=0, window=100_000, tmp_path=tmp_path)
        cm.evidence_store = EvidenceStore(base_dir=tmp_path)
        long_output = "\n".join(f"{'x' * 50} line {i}" for i in range(400))
        result = cm.compress_immediate("call_abc", "bash", long_output)
        assert "call_abc" in result
        assert cm.evidence_store.load("call_abc") is not None

    def test_compress_immediate_hint_in_output(self, tmp_path):
        cm = self._make_cm(used=0, window=100_000, tmp_path=tmp_path)
        long_output = "a" * 20_000
        result = cm.compress_immediate("call_xyz", "unknown_tool", long_output)
        assert "recall_evidence" in result
        assert "call_xyz" in result

    def test_compress_batch_preserves_recent(self, tmp_path):
        cm = self._make_cm(used=0, window=100_000, tmp_path=tmp_path)
        big_content = "\n".join(f"{'x' * 50} line {i}" for i in range(400))
        messages = [
            {"role": "tool", "tool_call_id": f"c{i}", "content": big_content} for i in range(8)
        ]
        result = cm.compress_batch(messages)
        # last 5 must be unchanged
        for msg in result[-5:]:
            assert msg["content"] == big_content
        # earlier ones must be compressed
        for msg in result[:3]:
            assert len(msg["content"]) < len(big_content)

    def test_compress_batch_short_content_untouched(self, tmp_path):
        cm = self._make_cm(used=0, window=100_000, tmp_path=tmp_path)
        messages = [{"role": "tool", "tool_call_id": f"c{i}", "content": "short"} for i in range(8)]
        result = cm.compress_batch(messages)
        for msg in result:
            assert msg["content"] == "short"

    def test_compress_batch_non_tool_messages_untouched(self, tmp_path):
        cm = self._make_cm(used=0, window=100_000, tmp_path=tmp_path)
        big = "x" * 20_000
        messages = [
            {"role": "user", "content": big},
            {"role": "assistant", "content": big},
        ]
        result = cm.compress_batch(messages)
        assert result[0]["content"] == big
        assert result[1]["content"] == big


class TestBuiltinTools:
    def _make_store(self, tmp_path):
        from sre_agent.core.evidence_store import EvidenceStore

        return EvidenceStore(base_dir=tmp_path)

    def _make_scratchpad(self):
        from sre_agent.core.scratchpad import Scratchpad

        return Scratchpad()

    def test_update_scratchpad_returns_summary(self, tmp_path):
        from sre_agent.core.builtin_tools import UpdateScratchpadTool
        from sre_agent.core.tool import ToolResultStatus

        sp = self._make_scratchpad()
        tool = UpdateScratchpadTool(sp)
        result = tool.invoke(
            {
                "findings": ["pod OOMKilled"],
                "hypotheses": ["memory leak in app"],
                "ruled_out": ["disk issue"],
                "next_steps": ["check heap dump"],
            }
        )
        assert result.status == ToolResultStatus.SUCCESS
        assert "1 条发现" in result.data
        assert "1 个假设" in result.data

    def test_update_scratchpad_mutates_scratchpad(self, tmp_path):
        from sre_agent.core.builtin_tools import UpdateScratchpadTool

        sp = self._make_scratchpad()
        tool = UpdateScratchpadTool(sp)
        tool.invoke({"findings": ["cpu spike"], "next_steps": ["check top"]})
        assert "cpu spike" in sp.findings
        assert "check top" in sp.next_steps

    def test_update_scratchpad_partial_params(self, tmp_path):
        from sre_agent.core.builtin_tools import UpdateScratchpadTool
        from sre_agent.core.tool import ToolResultStatus

        sp = self._make_scratchpad()
        tool = UpdateScratchpadTool(sp)
        result = tool.invoke({"findings": ["latency up"]})
        assert result.status == ToolResultStatus.SUCCESS
        assert "1 条发现" in result.data

    def test_recall_evidence_success(self, tmp_path):
        from sre_agent.core.builtin_tools import RecallEvidenceTool
        from sre_agent.core.tool import ToolResultStatus

        store = self._make_store(tmp_path)
        store.save("call_001", "full raw output here")
        tool = RecallEvidenceTool(store)
        result = tool.invoke({"call_id": "call_001"})
        assert result.status == ToolResultStatus.SUCCESS
        assert result.data == "full raw output here"

    def test_recall_evidence_missing(self, tmp_path):
        from sre_agent.core.builtin_tools import RecallEvidenceTool
        from sre_agent.core.tool import ToolResultStatus

        store = self._make_store(tmp_path)
        tool = RecallEvidenceTool(store)
        result = tool.invoke({"call_id": "nonexistent"})
        assert result.status == ToolResultStatus.ERROR
        assert "nonexistent" in result.error

    def test_builtin_tools_openai_schema(self, tmp_path):
        from sre_agent.core.builtin_tools import make_builtin_tools

        sp = self._make_scratchpad()
        store = self._make_store(tmp_path)
        tools = make_builtin_tools(sp, store)
        schemas = [t.to_openai_tool() for t in tools]
        names = [s["function"]["name"] for s in schemas]
        assert "update_scratchpad" in names
        assert "recall_evidence" in names
        recall_schema = next(s for s in schemas if s["function"]["name"] == "recall_evidence")
        assert "call_id" in recall_schema["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Engine integration helpers
# ---------------------------------------------------------------------------


def _make_seq_llm(responses, token_counts, window=100_000):
    """Fake LLM that returns pre-programmed responses and token counts in order."""
    from sre_agent.core.llm import LLM

    class _SeqLLM(LLM):
        def __init__(self):
            self._r = list(responses)
            self._tc = list(token_counts)
            self.calls = []  # (messages, tools, tool_choice)

        def completion(self, messages, tools=None, tool_choice=None):
            self.calls.append((messages, tools, tool_choice))
            return self._r.pop(0) if self._r else ModelResponse(content="done")

        def count_tokens(self, messages, tools=None):
            return self._tc.pop(0) if self._tc else 0

        def get_context_window_size(self):
            return window

    return _SeqLLM()


def _make_cm(llm, tmp_path):
    """Return (ContextManager, scratchpad, evidence_store) backed by tmp_path."""
    from sre_agent.core.context_manager import ContextManager
    from sre_agent.core.evidence_store import EvidenceStore
    from sre_agent.core.scratchpad import Scratchpad

    store = EvidenceStore(base_dir=tmp_path)
    sp = Scratchpad()
    return ContextManager(llm=llm, evidence_store=store, scratchpad=sp, toolsets={}), sp, store


class TestEngineIntegration:
    def test_convergence_triggered(self, tmp_path):
        llm = _make_seq_llm(
            responses=[ModelResponse(content="forced conclusion")],
            token_counts=[91_000],  # 91 % of 100 k → CONVERGE
            window=100_000,
        )
        cm, _, _ = _make_cm(llm, tmp_path)
        engine = Engine(llm=llm, tool_executor=ToolExecutor(), context_manager=cm)

        result = engine.call([{"role": "user", "content": "investigate"}])

        assert result.converged is True
        assert result.answer == "forced conclusion"
        assert len(llm.calls) == 1
        _, _, tool_choice = llm.calls[0]
        assert tool_choice == "none"

    def test_builtin_tool_routing(self, tmp_path):
        import json

        update_call = {
            "id": "tc_sp",
            "type": "function",
            "function": {
                "name": "update_scratchpad",
                "arguments": json.dumps({"findings": ["cpu spike on node-1"]}),
            },
        }
        llm = _make_seq_llm(
            responses=[
                ModelResponse(tool_calls=[update_call]),
                ModelResponse(content="done"),
            ],
            token_counts=[0, 0],
        )
        cm, sp, _ = _make_cm(llm, tmp_path)
        engine = Engine(llm=llm, tool_executor=ToolExecutor(), context_manager=cm)

        result = engine.call([{"role": "user", "content": "investigate"}])

        assert "cpu spike on node-1" in sp.findings
        assert result.answer == "done"
        assert result.converged is False

    def test_immediate_compression(self, tmp_path):
        big = "\n".join(f"{'x' * 60} line {i}" for i in range(300))  # ~20 k chars > 16 k threshold

        tool_call = {
            "id": "tc_big",
            "type": "function",
            "function": {"name": "echo_tool", "arguments": "{}"},
        }

        class _EchoTool(Tool):
            def __init__(self):
                super().__init__(
                    "echo_tool", "echoes large output", {"type": "object", "properties": {}}
                )

            def _invoke(self, params):
                return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=big)

        executor = ToolExecutor()
        executor.register(_EchoTool())

        llm = _make_seq_llm(
            responses=[
                ModelResponse(tool_calls=[tool_call]),
                ModelResponse(content="done"),
            ],
            token_counts=[0, 0],
        )
        cm, _, store = _make_cm(llm, tmp_path)
        engine = Engine(llm=llm, tool_executor=executor, context_manager=cm)

        messages = [{"role": "user", "content": "q"}]
        engine.call(messages)

        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert tool_msgs, "no tool message found in messages"
        assert len(tool_msgs[0]["content"]) < len(big)
        assert store.load("tc_big") is not None

    def test_scratchpad_injected_into_system_message(self, tmp_path):
        import json

        update_call = {
            "id": "tc_inject",
            "type": "function",
            "function": {
                "name": "update_scratchpad",
                "arguments": json.dumps({"findings": ["memory leak detected"]}),
            },
        }
        llm = _make_seq_llm(
            responses=[
                ModelResponse(tool_calls=[update_call]),
                ModelResponse(content="done"),
            ],
            token_counts=[0, 0],
        )
        cm, _, _ = _make_cm(llm, tmp_path)
        engine = Engine(llm=llm, tool_executor=ToolExecutor(), context_manager=cm)

        messages = [
            {"role": "system", "content": "you are an SRE agent"},
            {"role": "user", "content": "investigate"},
        ]
        engine.call(messages)

        assert len(llm.calls) == 2
        second_sys_content = llm.calls[1][0][0]["content"]
        assert "memory leak detected" in second_sys_content
        # Original list must NOT be mutated by scratchpad injection
        assert "memory leak detected" not in messages[0]["content"]

    def test_compress_batch_triggered(self, tmp_path):
        big = "\n".join(f"{'x' * 60} line {i}" for i in range(300))  # ~20 k chars > 16 k threshold

        pre = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
        for i in range(8):
            pre.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"old{i}",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{}"},
                        }
                    ],
                }
            )
            pre.append({"role": "tool", "tool_call_id": f"old{i}", "content": big})

        llm = _make_seq_llm(
            responses=[ModelResponse(content="done")],
            token_counts=[75_000],  # 75 % of 100 k → COMPRESS
            window=100_000,
        )
        cm, _, _ = _make_cm(llm, tmp_path)
        engine = Engine(llm=llm, tool_executor=ToolExecutor(), context_manager=cm)
        engine.call(pre)

        tool_msgs = [m for m in pre if m.get("role") == "tool"]
        assert len(tool_msgs) == 8
        # Oldest 3 (beyond recent-5 window) must be compressed
        for m in tool_msgs[:3]:
            assert len(m["content"]) < len(big), "old tool message should have been compressed"
        # Recent 5 must be unchanged
        for m in tool_msgs[3:]:
            assert m["content"] == big, "recent tool message should be preserved"
