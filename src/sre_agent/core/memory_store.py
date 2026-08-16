"""跨会话调查记忆的数据模型、提取、持久化与语义检索。"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sre_agent.core.embedder import Embedder
from sre_agent.core.llm import LLM
from sre_agent.core.scratchpad import Scratchpad
from sre_agent.utils.jinja import load_prompt

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "sre_investigations"
_INDEX_META_FILE = "index_meta.json"


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
        root_cause、resolution、evidence_refs 对语义检索本身没有用处（它们不进
        embedding），存在这里纯粹是为了 JSON 归档缺失时 _reconstruct_summary()
        仍能还原出记忆中最有价值的部分——根因和解决方案无法从 document 反推。
        """

        return {
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "evidence_refs": ",".join(self.evidence_refs),
            "tools_used": ",".join(self.tools_used),
            "tags": ",".join(self.tags),
            "timestamp": self.timestamp,
            "converged": self.converged,
        }


def _generate_investigation_id() -> str:
    """生成格式为 inv_{timestamp}_{short_hash} 的唯一 ID。"""

    now = datetime.now(tz=UTC)
    ts = now.strftime("%Y%m%d_%H%M%S")
    # 取微秒和时间戳组合后的 hash 前 8 位，确保同一秒内多次调用不冲突。
    raw = f"{now.isoformat()}-{id(now)}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"inv_{ts}_{short_hash}"


class MemoryStore:
    """协调 Embedder、LLM 和 ChromaDB，实现调查摘要的提取、持久化与语义检索。

    双写策略：每条 InvestigationSummary 同时写入 ChromaDB（用于检索）和
    JSON 文件（无损归档）。ChromaDB 是索引层，JSON 是真相源——索引是纯派生数据，
    任何时候都能由 :meth:`reindex` 从归档重建，构造时也会自动校验并按需重建。
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
        self._meta_path = self._memory_dir / _INDEX_META_FILE

        self._chroma_dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=None,
        )

        self._ensure_index_current()

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
                query_embeddings=[query_embedding],  # type: ignore[arg-type]
                n_results=self._top_k,
                include=["documents", "metadatas", "distances"],
            )

            summaries: list[InvestigationSummary] = []

            ids = (results.get("ids") or [[]])[0]
            documents = (results.get("documents") or [[]])[0]
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]

            for i, inv_id in enumerate(ids):
                # ChromaDB 返回的 distance 越小越相似；转换为 0-1 分数便于阈值过滤。
                distance = distances[i] if distances else 0.0
                score = 1.0 - float(distance)

                if score < self._score_threshold:
                    continue

                metadata: dict[str, Any] = dict(metadatas[i]) if metadatas else {}
                doc = documents[i] if documents else None
                summary = self._reconstruct_summary(inv_id, doc, metadata, score)
                summaries.append(summary)

            return summaries
        except Exception:
            logger.warning("调查记忆检索失败，跳过历史注入", exc_info=True)
            return []

    def reindex(self) -> int:
        """丢弃现有索引，用 JSON 归档重新 embed 并写回 ChromaDB，返回重建的条目数。

        索引是纯派生数据，重建一律以归档为准：归档里没有的条目会被清掉——它们本就
        读不回完整内容，换模型后向量也已失效。解析失败的单个归档只跳过并告警，
        不让一条坏文件毁掉整次重建。
        """

        summaries: list[InvestigationSummary] = []
        for path in sorted(self._archive_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                summaries.append(InvestigationSummary(**data))
            except Exception:
                logger.warning("归档 %s 解析失败，重建索引时跳过", path.name, exc_info=True)

        # 整体删除重建而非逐条 upsert：换模型后维度可能改变，向已有集合写入不同
        # 维度的向量会直接报错，且旧集合里的残留条目也需要一并清掉。
        self._client.delete_collection(name=_COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=None,
        )

        if summaries:
            texts = [s.to_embedding_text() for s in summaries]
            # 一次性批量 embed，避免按条反复调用模型。
            embeddings = self._embedder.embed(texts)
            self._collection.upsert(
                ids=[s.id for s in summaries],
                embeddings=embeddings,  # type: ignore[arg-type]
                documents=texts,
                metadatas=[s.to_chroma_metadata() for s in summaries],
            )

        self._write_index_meta()
        return len(summaries)

    def _ensure_index_current(self) -> None:
        """校验索引与归档是否仍然一致，不一致则重建。

        两种失效场景都是静默的，所以必须在构造时主动查：
        1. 换了 embedding 模型——向量只在同一模型下可比。维度不同会让 upsert 和
           query 直接抛异常，被 save/recall 的兜底 except 吞成"没有记忆"；维度恰好
           相同则更隐蔽，不报错但相似度退化成噪声，再被阈值滤掉。
        2. 索引与归档条数对不上——chroma 目录被删、或某次 upsert 失败只留下了归档。

        重建失败不抛出：记忆检索属于增强功能，索引出问题不该阻断 MemoryStore 的
        构造，更不该阻断调查流程。
        """

        try:
            self._check_and_rebuild_index()
        except Exception:
            logger.warning("索引校验或重建失败，历史记忆本次可能无法被检索到", exc_info=True)

    def _check_and_rebuild_index(self) -> None:
        """_ensure_index_current 的实际逻辑，异常由调用方统一兜底。"""

        recorded = self._read_index_meta()
        current = self._embedder.model_id
        archive_count = sum(1 for _ in self._archive_dir.glob("*.json"))
        indexed_count = self._collection.count()

        if recorded == current and archive_count == indexed_count:
            return

        if recorded is None and archive_count == 0 and indexed_count == 0:
            # 全新的 memory 目录，没有可重建的内容，记下模型标识即可。
            self._write_index_meta()
            return

        if recorded != current:
            reason = (
                f"索引所用 embedding 模型未知（{_INDEX_META_FILE} 缺失或损坏）"
                if recorded is None
                else f"embedding 模型已由 {recorded} 变为 {current}"
            )
        else:
            reason = f"索引与归档不一致（归档 {archive_count} 条，索引 {indexed_count} 条）"

        logger.info("%s，正在用 JSON 归档重建索引", reason)
        rebuilt = self.reindex()
        logger.info("索引重建完成，共 %d 条记忆", rebuilt)

    def _read_index_meta(self) -> str | None:
        """读取建索引时使用的 embedding 模型标识；文件缺失或损坏时返回 None。"""

        if not self._meta_path.exists():
            return None
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
            model = data.get("embedding_model")
        except Exception:
            # 元数据损坏按"来源未知"处理，触发一次重建即可自愈。
            return None
        return model if isinstance(model, str) else None

    def _write_index_meta(self) -> None:
        """记录当前索引由哪个 embedding 模型建成。"""

        self._meta_path.write_text(
            json.dumps({"embedding_model": self._embedder.model_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
            lines = [line for line in lines[1:] if not line.strip().startswith("```")]
            cleaned = "\n".join(lines)

        extracted: dict[str, Any] = json.loads(cleaned)

        inv_id = _generate_investigation_id()
        now = datetime.now(tz=UTC).isoformat()

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
        """将 InvestigationSummary 双写到 JSON 归档和 ChromaDB。

        写入顺序是有意的：JSON 是真相源，必须先于索引落盘。若顺序相反且中途失败，
        Chroma 里会残留一条查得到却读不回归档的记忆，recall() 只能走降级还原，
        把可能错位的内容注入下一次调查；反过来失败只是这条记忆检索不到，不会污染
        上下文。embedding 在两次写入之前算好，让最可能失败的一步不留下半套数据。
        """

        embedding_text = summary.to_embedding_text()
        embedding = self._embedder.embed([embedding_text])[0]

        # 先写临时文件再原子改名：进程若在写入中途被杀，留下的是 .tmp 而不是半截
        # JSON——后者会让 _reconstruct_summary() 解析失败，进而使整批 recall 结果被丢弃。
        json_path = self._archive_dir / f"{summary.id}.json"
        tmp_path = self._archive_dir / f"{summary.id}.json.tmp"
        tmp_path.write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(json_path)

        try:
            self._collection.upsert(
                ids=[summary.id],
                embeddings=[embedding],  # type: ignore[arg-type]
                documents=[embedding_text],
                metadatas=[summary.to_chroma_metadata()],
            )
        except Exception:
            # 归档已落盘，这条记忆不会丢，只是检索不到。显式告警而不是让调用方，以为整条链路都成功了。
            logger.warning(
                "调查 %s 已归档但索引写入失败，该条记忆无法被 recall 检索到",
                summary.id,
                exc_info=True,
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
        evidence_refs_str: str = metadata.get("evidence_refs", "")

        return InvestigationSummary(
            id=inv_id,
            question=question,
            conclusion=conclusion,
            # 根因和解决方案没有进 embedding，document 里不存在，只能取自 metadata。
            root_cause=metadata.get("root_cause", ""),
            resolution=metadata.get("resolution", ""),
            key_evidence=key_evidence,
            tools_used=tools_str.split(",") if tools_str else [],
            tags=tags_str.split(",") if tags_str else [],
            timestamp=metadata.get("timestamp", ""),
            evidence_refs=evidence_refs_str.split(",") if evidence_refs_str else [],
            converged=bool(metadata.get("converged", False)),
        )
