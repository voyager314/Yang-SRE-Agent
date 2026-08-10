"""Token 预算管理与上下文压缩。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .evidence_store import EvidenceStore
from .llm import LLM
from .scratchpad import Scratchpad
from .tool import Toolset

_IMMEDIATE_CHAR_THRESHOLD = 16_000  # ~4K tokens at 4 chars/token
_RECENT_CALLS_TO_KEEP = 5


class BudgetStatus(StrEnum):
    NORMAL = "normal"
    COMPRESS = "compress"
    CONVERGE = "converge"


class ContextManager:
    """协调 token 预算检查、即时压缩和批量压缩。"""

    def __init__(
        self,
        llm: LLM,
        evidence_store: EvidenceStore,
        scratchpad: Scratchpad,
        toolsets: dict[str, Toolset],
        compress_threshold: float = 0.70,
        converge_threshold: float = 0.90,
    ) -> None:
        self.llm = llm
        self.evidence_store = evidence_store
        self.scratchpad = scratchpad
        self.toolsets = toolsets
        self.compress_threshold = compress_threshold
        self.converge_threshold = converge_threshold

    # ------------------------------------------------------------------
    # 3.2 预算检查
    # ------------------------------------------------------------------

    def check_budget(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> BudgetStatus:
        """根据当前对话估算 token 占用，返回预算状态。"""
        used = self.llm.count_tokens(messages, tools)
        window = self.llm.get_context_window_size()
        ratio = used / window if window > 0 else 0.0
        if ratio >= self.converge_threshold:
            return BudgetStatus.CONVERGE
        if ratio >= self.compress_threshold:
            return BudgetStatus.COMPRESS
        return BudgetStatus.NORMAL

    # ------------------------------------------------------------------
    # 3.3 即时压缩
    # ------------------------------------------------------------------

    def compress_immediate(
        self,
        call_id: str,
        tool_name: str,
        raw_output: str,
    ) -> str:
        """超过字符阈值时压缩并持久化原始输出，否则直接返回。"""
        if len(raw_output) <= _IMMEDIATE_CHAR_THRESHOLD:
            return raw_output

        self.evidence_store.save(call_id, raw_output)

        toolset = self.toolsets.get(tool_name)
        if toolset is not None:
            compressed = toolset.compress(tool_name, raw_output)
        else:
            compressed = _default_compress(raw_output)

        recall_hint = f"\n[原始输出已存储，call_id={call_id}，可用 recall_evidence 获取完整内容]"
        return compressed + recall_hint

    # ------------------------------------------------------------------
    # 3.4 批量压缩
    # ------------------------------------------------------------------

    def compress_batch(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """压缩旧 tool 消息中较大的内容，保留最近 N 条 tool 调用不变。"""
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        recent_set = set(tool_indices[-_RECENT_CALLS_TO_KEEP:])

        result: list[dict[str, Any]] = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool" and i not in recent_set:
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > _IMMEDIATE_CHAR_THRESHOLD:
                    call_id = msg.get("tool_call_id", f"batch_{i}")
                    tool_name = msg.get("name", "")
                    compressed = self.compress_immediate(call_id, tool_name, content)
                    result.append({**msg, "content": compressed})
                    continue
            result.append(msg)
        return result


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------


def _default_compress(text: str, head: int = 20, tail: int = 5) -> str:
    lines = text.splitlines()
    total = len(lines)
    if total <= head + tail:
        return text
    kept = lines[:head] + [f"... [已折叠 {total - head - tail} 行] ..."] + lines[-tail:]
    return "\n".join(kept)
