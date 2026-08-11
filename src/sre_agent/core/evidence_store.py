"""工具完整输出的本地持久化与按需回取（Tier 3 证据库）。"""

from __future__ import annotations

from pathlib import Path


class EvidenceStore:
    """将压缩前的完整工具输出落盘，并支持按 call_id 回取。

    文件路径：``<base_dir>/<call_id>``，纯文本，无元数据包装。
    生命周期与进程相同——不主动清理，但不保证跨会话可用。
    """

    def __init__(self, base_dir: Path | str = Path("temp/tool-results")):
        self._base_dir = Path(base_dir)

    def save(self, call_id: str, content: str) -> Path:
        """将完整输出写入磁盘，返回文件路径。"""

        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._base_dir / call_id
        path.write_text(content, encoding="utf-8")
        return path

    def clear(self) -> None:
        """删除所有已存储的证据文件。"""

        if self._base_dir.exists():
            for f in self._base_dir.iterdir():
                if f.is_file():
                    f.unlink()

    def load(self, call_id: str) -> str | None:
        """读取指定 call_id 的完整输出；文件不存在时返回 None。"""

        path = self._base_dir / call_id
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
