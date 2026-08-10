"""模型可调用的内置工具：scratchpad 更新与证据召回。"""

from __future__ import annotations

from typing import Any

from .evidence_store import EvidenceStore
from .scratchpad import Scratchpad
from .tool import StructuredToolResult, Tool, ToolResultStatus

_LIST_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
    "default": [],
}


class UpdateScratchpadTool(Tool):
    """让模型以结构化方式记录调查进展，替代自由文本推理。"""

    def __init__(self, scratchpad: Scratchpad) -> None:
        self._scratchpad = scratchpad
        super().__init__(
            name="update_scratchpad",
            description=(
                "更新调查记录本。调用此工具将当前的发现、假设、已排除原因和下一步计划"
                "写入结构化记录，这些信息会自动注入后续每一轮系统提示。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "findings": {**_LIST_SCHEMA, "description": "已确认的事实和观测结果"},
                    "hypotheses": {**_LIST_SCHEMA, "description": "当前正在验证的假设"},
                    "ruled_out": {**_LIST_SCHEMA, "description": "已排除的原因或假设"},
                    "next_steps": {**_LIST_SCHEMA, "description": "计划执行的下一步操作"},
                },
                "required": [],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        self._scratchpad.update(
            findings=params.get("findings", []),
            hypotheses=params.get("hypotheses", []),
            ruled_out=params.get("ruled_out", []),
            next_steps=params.get("next_steps", []),
        )
        summary = (
            f"记录本已更新：{len(self._scratchpad.findings)} 条发现，"
            f"{len(self._scratchpad.hypotheses)} 个假设，"
            f"{len(self._scratchpad.ruled_out)} 个已排除，"
            f"{len(self._scratchpad.next_steps)} 个下一步。"
        )
        return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=summary)


class RecallEvidenceTool(Tool):
    """从证据库加载之前被压缩过的完整工具输出。"""

    def __init__(self, evidence_store: EvidenceStore) -> None:
        self._store = evidence_store
        super().__init__(
            name="recall_evidence",
            description=(
                "根据 call_id 从证据库中取回完整的工具输出原文。"
                "当压缩摘要信息不足以支撑决策时使用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "call_id": {
                        "type": "string",
                        "description": "工具调用 ID，见压缩摘要末尾的 call_id 字段",
                    },
                },
                "required": ["call_id"],
            },
        )

    def _invoke(self, params: dict[str, Any]) -> StructuredToolResult:
        call_id = params.get("call_id", "")
        content = self._store.load(call_id)
        if content is None:
            return StructuredToolResult(
                status=ToolResultStatus.ERROR,
                error=f"证据库中不存在 call_id={call_id!r} 的记录",
            )
        return StructuredToolResult(status=ToolResultStatus.SUCCESS, data=content)


def make_builtin_tools(
    scratchpad: Scratchpad,
    evidence_store: EvidenceStore,
) -> list[Tool]:
    """返回所有内置工具实例，方便引擎批量注册。"""
    return [
        UpdateScratchpadTool(scratchpad),
        RecallEvidenceTool(evidence_store),
    ]
