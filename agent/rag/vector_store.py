"""向量索引 —— 语义检索路。

VectorStore 是协议（Protocol），上层检索器只依赖该协议：
  - 当前实现 NumpyVectorStore：暴力余弦检索，几十到几千个分块完全够快，零额外依赖；
  - 未来若分块规模变大，可新增 FaissVectorStore 实现同一协议，上层零改动。

向量在写入时即做 L2 归一化，检索时点积即为余弦相似度。
"""

from typing import List, Optional, Protocol, Sequence, Tuple

import numpy as np


class VectorStore(Protocol):
    """向量索引接口：可替换后端（numpy / faiss / 其他）。"""

    def add(self, ids: Sequence[str], vectors: np.ndarray) -> None: ...

    def search(
        self, query_vector: np.ndarray, top_k: int, min_score: float = 0.0
    ) -> List[Tuple[str, float]]: ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """按行做 L2 归一化，零向量保持为零。"""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class NumpyVectorStore:
    """纯 numpy 实现的暴力余弦检索。"""

    def __init__(self) -> None:
        self._matrix: Optional[np.ndarray] = None
        self._ids: List[str] = []

    @property
    def size(self) -> int:
        return len(self._ids)

    def add(self, ids: Sequence[str], vectors: np.ndarray) -> None:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.shape[0] != len(ids):
            raise ValueError(f"向量数量({matrix.shape[0]})与 id 数量({len(ids)})不一致")

        self._matrix = _normalize(matrix)
        self._ids = list(ids)

    def search(
        self, query_vector: np.ndarray, top_k: int = 5, min_score: float = 0.0
    ) -> List[Tuple[str, float]]:
        """返回相似度高于 min_score 的前 top_k 条。

        min_score 用于过滤无关结果（余弦相似度为 0 表示完全正交），
        否则「查不到」会被伪装成「返回若干低相关片段」。
        """
        if self._matrix is None or not self._ids:
            return []

        query = _normalize(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
        similarities = self._matrix @ query

        # 先按相似度降序，再按下标升序，保证同分结果顺序确定
        order = sorted(range(len(self._ids)), key=lambda i: (-float(similarities[i]), i))
        hits = [(self._ids[i], float(similarities[i])) for i in order]
        return [item for item in hits if item[1] > min_score][:top_k]
