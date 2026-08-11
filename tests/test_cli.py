"""CLI REPL 及斜杠命令的单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from sre_agent.cli import _SessionState, _cmd_model, _cmd_new, _dispatch_slash, app
from sre_agent.config import Config
from sre_agent.core.context_manager import ContextManager
from sre_agent.core.engine import Engine
from sre_agent.core.evidence_store import EvidenceStore
from sre_agent.core.llm import DefaultLLM
from sre_agent.core.scratchpad import Scratchpad

runner = CliRunner()


def _make_state(tmp_path) -> _SessionState:
    """构造一个用于测试的 _SessionState。"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "model: test-model\n"
        "models:\n"
        "  fast:\n"
        "    model: gpt-4o-mini\n"
        "    api_base: https://fast.example.com\n"
        "  slow:\n"
        "    model: claude-opus\n"
        "    api_key: sk-test\n"
    )
    config = Config(_config_file=str(config_file))

    llm = DefaultLLM(model="test-model")
    evidence_store = EvidenceStore(base_dir=tmp_path / "evidence")
    scratchpad = Scratchpad()
    cm = ContextManager(
        llm=llm,
        evidence_store=evidence_store,
        scratchpad=scratchpad,
        toolsets={},
    )
    engine = MagicMock(spec=Engine)
    engine.llm = llm
    engine.context_manager = cm

    mgr = MagicMock()
    mgr.toolsets = []

    messages = [{"role": "system", "content": "system prompt"}]
    return _SessionState(engine, config, "system prompt", mgr, messages)


class TestDispatchSlash:
    def test_exit_returns_false(self, tmp_path):
        state = _make_state(tmp_path)
        assert _dispatch_slash("/exit", state) is False

    def test_quit_returns_false(self, tmp_path):
        state = _make_state(tmp_path)
        assert _dispatch_slash("/quit", state) is False

    def test_help_returns_none(self, tmp_path):
        state = _make_state(tmp_path)
        assert _dispatch_slash("/help", state) is None

    def test_unknown_command_returns_none(self, tmp_path):
        state = _make_state(tmp_path)
        assert _dispatch_slash("/nonexistent", state) is None

    def test_new_returns_none(self, tmp_path):
        state = _make_state(tmp_path)
        state.messages.append({"role": "user", "content": "hello"})
        assert _dispatch_slash("/new", state) is None

    def test_model_returns_none(self, tmp_path):
        state = _make_state(tmp_path)
        assert _dispatch_slash("/model", state) is None

    def test_case_insensitive(self, tmp_path):
        state = _make_state(tmp_path)
        assert _dispatch_slash("/EXIT", state) is False


class TestCmdNew:
    def test_clears_messages(self, tmp_path):
        state = _make_state(tmp_path)
        state.messages.append({"role": "user", "content": "hello"})
        state.messages.append({"role": "assistant", "content": "hi"})
        assert len(state.messages) == 3

        _cmd_new(state)

        assert len(state.messages) == 1
        assert state.messages[0]["role"] == "system"

    def test_clears_scratchpad(self, tmp_path):
        state = _make_state(tmp_path)
        cm = state.engine.context_manager
        cm.scratchpad.update(findings=["something"])
        assert not cm.scratchpad.is_empty()

        _cmd_new(state)

        assert cm.scratchpad.is_empty()

    def test_clears_evidence(self, tmp_path):
        state = _make_state(tmp_path)
        cm = state.engine.context_manager
        cm.evidence_store.save("test-call", "raw output data")
        assert cm.evidence_store.load("test-call") is not None

        _cmd_new(state)

        assert cm.evidence_store.load("test-call") is None


class TestCmdModel:
    def test_switch_to_registered_model(self, tmp_path):
        state = _make_state(tmp_path)
        llm = state.engine.llm

        _cmd_model("fast", state)

        assert llm.model == "gpt-4o-mini"
        assert llm.api_base == "https://fast.example.com"
        assert state.model_key == "fast"

    def test_switch_preserves_messages(self, tmp_path):
        state = _make_state(tmp_path)
        state.messages.append({"role": "user", "content": "question"})
        original_len = len(state.messages)

        _cmd_model("fast", state)

        assert len(state.messages) == original_len
        assert state.messages[1]["content"] == "question"

    def test_switch_to_registered_model_with_api_key(self, tmp_path):
        state = _make_state(tmp_path)
        llm = state.engine.llm

        _cmd_model("slow", state)

        assert llm.model == "claude-opus"
        assert llm.api_key == "sk-test"

    def test_switch_to_unregistered_model(self, tmp_path):
        state = _make_state(tmp_path)
        llm = state.engine.llm

        _cmd_model("some-random-model", state)

        assert llm.model == "some-random-model"
        assert llm.api_key is None
        assert llm.api_base is None

    def test_show_current_model_no_args(self, tmp_path, capsys):
        state = _make_state(tmp_path)
        _cmd_model("", state)


class TestCLIEntryPoint:
    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "question" in result.output.lower()
        assert "--print" in result.output

    def test_print_mode_requires_question(self):
        with patch("sre_agent.cli._build_engine") as mock_build:
            mock_engine = MagicMock()
            mock_build.return_value = (mock_engine, "sys prompt", MagicMock())
            result = runner.invoke(app, ["-p"])
        assert result.exit_code == 1


class TestEvidenceStoreClear:
    def test_clear_removes_files(self, tmp_path):
        store = EvidenceStore(base_dir=tmp_path / "evidence")
        store.save("call-1", "data 1")
        store.save("call-2", "data 2")
        assert store.load("call-1") is not None

        store.clear()

        assert store.load("call-1") is None
        assert store.load("call-2") is None

    def test_clear_on_empty_store(self, tmp_path):
        store = EvidenceStore(base_dir=tmp_path / "evidence")
        store.clear()


class TestScratchpadClear:
    def test_clear_resets_all_fields(self):
        pad = Scratchpad()
        pad.update(
            findings=["f1"],
            hypotheses=["h1"],
            ruled_out=["r1"],
            next_steps=["n1"],
        )
        assert not pad.is_empty()

        pad.clear()

        assert pad.is_empty()
        assert pad.findings == []
        assert pad.hypotheses == []
        assert pad.ruled_out == []
        assert pad.next_steps == []
