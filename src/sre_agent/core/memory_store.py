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


class MemoryStore:
    """协调 Embedder、LLM 和 ChromaDB，实现调查摘要的提取、持久化与语义检索。

    双写策略：每条 InvestigationSummary 同时写入 ChromaDB（用于检索）和
    JSON 文件（无损归档）。ChromaDB 是索引层，JSON 是真相源。
    """

    def __init__(
        self,
        embedder: Embedder,
        llm: LLM,
        memory_dir: str | Path,
        top_k: int = 3,
        score_threshold: float = 0.6,
    ) -> None:
        import chromadb

        self._embedder = embedder
        self._llm = llm
        self._top_k = top_k
        self._score_threshold = score_threshold

        self._memory_dir = Path(memory_dir)
        self._chroma_dir = self._memory_dir / "chroma"
        self._archive_dir = self._memory_dir / "investigations"

        self._chroma_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name="sre_investigations",
            embedding_function=None,
        )

    def save_investigation(
        self,
        question: str,
        answer: str,
        scratchpad: Scratchpad,
        tool_calls: list[dict[str, Any]],
        evidence_refs: list[str],
        converged: bool = False,
    ) -> InvestigationSummary | None:
        """提取调查摘要并持久化到 ChromaDB 和 JSON 归档。

        整个流程包装在 try/except 中——提取或存储失败只记录警告，不中断调查流程。
        """

        try:
            summary = self._extract_summary(
                question, answer, scratchpad, tool_calls, evidence_refs, converged
            )
            self._persist(summary)
            return summary
        except Exception:
            logger.warning("调查摘要提取或存储失败，跳过记忆保存", exc_info=True)
            return None

    def recall(self, query: str) -> list[InvestigationSummary]:
        """按语义相似度检索相关的历史调查摘要。

        返回相似度分数高于阈值的 top-k 条结果，collection 为空时返回空列表。
        """

        try:
            if self._collection.count() == 0:
                return []

            query_embedding = self._embedder.embed([query])[0]

            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=self._top_k,
                include=["documents", "metadatas", "distances"],
            )

            summaries: list[InvestigationSummary] = []

            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for i, inv_id in enumerate(ids):
                # ChromaDB 返回的 distance 越小越相似；转换为 0-1 分数便于阈值过滤。
                distance = distances[i] if distances else 0.0
                score = 1.0 - distance

                if score < self._score_threshold:
                    continue

                metadata = metadatas[i] if metadatas else {}
                summary = self._reconstruct_summary(inv_id, documents[i], metadata, score)
                summaries.append(summary)

            return summaries
        except Exception:
            logger.warning("调查记忆检索失败，跳过历史注入", exc_info=True)
            return []

    def _extract_summary(
        self,
        question: str,
        answer: str,
        scratchpad: Scratchpad,
        tool_calls: list[dict[str, Any]],
        evidence_refs: list[str],
        converged: bool,
    ) -> InvestigationSummary:
        """调用 LLM 从调查上下文中提取结构化摘要。"""

        scratchpad_yaml = scratchpad.to_yaml() if not scratchpad.is_empty() else "（无记录）"

        tool_names = []
        for tc in tool_calls:
            name = tc.get("name", "") or tc.get("function", {}).get("name", "")
            if name and name not in tool_names:
                tool_names.append(name)

        tool_calls_summary = ", ".join(tool_names) if tool_names else "（无工具调用）"

        extraction_prompt = load_prompt(
            "extract_summary",
            {
                "question": question,
                "answer": answer,
                "scratchpad_yaml": scratchpad_yaml,
                "tool_calls_summary": tool_calls_summary,
            },
        )

        response = self._llm.completion(
            messages=[{"role": "user", "content": extraction_prompt}],
            tool_choice="none",
        )

        raw_content = response.content or ""
        # 去除可能的 markdown 代码块围栏。
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # 去掉首行（```json 或 ```）和末行（```）。
            lines = [l for l in lines[1:] if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        extracted: dict[str, Any] = json.loads(cleaned)

        inv_id = _generate_investigation_id()
        now = datetime.now(tz=timezone.utc).isoformat()

        return InvestigationSummary(
            id=inv_id,
            question=question,
            conclusion=extracted.get("conclusion", answer[:200]),
            root_cause=extracted.get("root_cause", ""),
            resolution=extracted.get("resolution", ""),
            tools_used=tool_names,
            key_evidence=extracted.get("key_evidence", []),
            tags=extracted.get("tags", []),
            timestamp=now,
            evidence_refs=evidence_refs,
            converged=converged,
        )

    def _persist(self, summary: InvestigationSummary) -> None:
        """将 InvestigationSummary 双写到 ChromaDB 和 JSON 文件。"""

        embedding_text = summary.to_embedding_text()
        embedding = self._embedder.embed([embedding_text])[0]

        self._collection.upsert(
            ids=[summary.id],
            embeddings=[embedding],
            documents=[embedding_text],
            metadatas=[summary.to_chroma_metadata()],  # type: ignore[list-item]
        )

        json_path = self._archive_dir / f"{summary.id}.json"
        json_path.write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _reconstruct_summary(
        self,
        inv_id: str,
        document: str | None,
        metadata: dict[str, Any],
        score: float,
    ) -> InvestigationSummary:
        """从 ChromaDB 结果或 JSON 归档重建 InvestigationSummary。

        优先从 JSON 归档读取完整数据；归档不存在时从 ChromaDB 的
        document 和 metadata 做最大努力还原。
        """

        json_path = self._archive_dir / f"{inv_id}.json"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return InvestigationSummary(**data)

        # JSON 归档缺失时的降级还原。
        doc_lines = (document or "").split("\n")
        question = doc_lines[0] if doc_lines else ""
        conclusion = doc_lines[1] if len(doc_lines) > 1 else ""
        key_evidence = doc_lines[2:] if len(doc_lines) > 2 else []

        tools_str: str = metadata.get("tools_used", "")
        tags_str: str = metadata.get("tags", "")

        return InvestigationSummary(
            id=inv_id,
            question=question,
            conclusion=conclusion,
            key_evidence=key_evidence,
            tools_used=tools_str.split(",") if tools_str else [],
            tags=tags_str.split(",") if tags_str else [],
            timestamp=metadata.get("timestamp", ""),
            converged=bool(metadata.get("converged", False)),
        )
