"""跨会话调查记忆的数据模型、提取、持久化与语义检索。"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sre_agent.core.embedder import Embedder
from sre_agent.core.llm import LLM
from sre_agent.core.scratchpad import Scratchpad
from sre_agent.utils.jinja import load_prompt

logger = logging.getLogger(__name__)


class InvestigationSummary(BaseModel):
    """一次完整调查的结构化档案，作为长期记忆的基本单元。"""

    id: str
    question: str
    conclusion: str
    root_cause: str = ""
    resolution: str = ""
    tools_used: list[str] = []
    key_evidence: list[str] = []
    tags: list[str] = []
    timestamp: str = ""
    evidence_refs: list[str] = []
    converged: bool = False

    def to_embedding_text(self) -> str:
        """拼接语义核心字段，用作 embedding 输入。

        仅包含 question、conclusion 和 key_evidence，过滤掉 tools_used、tags
        等噪声字段，使向量聚焦于调查的语义内容。
        """

        parts = [self.question, self.conclusion]
        parts.extend(self.key_evidence)
        return "\n".join(parts)

    def to_chroma_metadata(self) -> dict[str, str | bool]:
        """提取适合 ChromaDB metadata 存储的扁平字典。

        ChromaDB metadata 值仅支持 str、int、float、bool，列表字段用逗号拼接。
        """

        return {
            "tools_used": ",".join(self.tools_used),
            "tags": ",".join(self.tags),
            "timestamp": self.timestamp,
            "converged": self.converged,
        }


def _generate_investigation_id() -> str:
    """生成格式为 inv_{timestamp}_{short_hash} 的唯一 ID。"""

    now = datetime.now(tz=timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    # 取微秒和时间戳组合后的 hash 前 8 位，确保同一秒内多次调用不冲突。
    raw = f"{now.isoformat()}-{id(now)}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"inv_{ts}_{short_hash}"
