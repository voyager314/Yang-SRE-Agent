"""文本嵌入向量生成的抽象接口及基于 sentence-transformers 的默认实现。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    """将文本转换为稠密向量的适配器协议。

    新增嵌入模型实现时只需实现该接口，MemoryStore 无需了解具体模型或推理框架。
    """

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本列表转换为对应的嵌入向量列表。

        返回值长度与输入列表一致，每个向量的维度取决于所用模型。
        """

        ...

    @property
    def model_id(self) -> str:
        """标识当前嵌入模型的字符串，供 MemoryStore 判断已建索引是否仍然可用。

        向量只在同一模型下可比，模型一变旧索引就必须整体重建。默认返回实现类名，
        具体实现应覆盖为真正的模型标识。
        """

        return type(self).__name__


class SentenceTransformerEmbedder(Embedder):
    """通过 sentence-transformers 加载本地模型生成嵌入向量。

    模型在首次调用 :meth:`embed` 时延迟加载，避免未使用 memory 功能时
    承担约 3GB 的模型加载开销。
    """

    def __init__(self, model_name: str = "Alibaba-NLP/gte-Qwen2-1.5B-instruct") -> None:
        self._model_name = model_name
        self._model: object | None = None

    @property
    def model_id(self) -> str:
        """返回 HuggingFace 模型标识，索引元数据据此判断是否需要重建。"""

        return self._model_name

    def _load_model(self) -> None:
        """加载 sentence-transformers 模型，首次运行时自动从 HuggingFace 下载。"""

        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self._model_name, trust_remote_code=True)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本列表编码为嵌入向量。

        首次调用时触发模型加载（含可能的网络下载），后续调用直接使用已加载的模型。
        """

        if self._model is None:
            self._load_model()

        # _load_model 之后 _model 不可能为 None，但 mypy 需要窄化。
        assert self._model is not None
        embeddings = self._model.encode(texts, convert_to_numpy=True)  # type: ignore[attr-defined]
        return [vec.tolist() for vec in embeddings]
