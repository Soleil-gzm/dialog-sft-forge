"""混合检索器 —— 统一的检索入口。

组合方式：
    BM25 关键词检索  ─┐
                      ├─→ RRF 融合 ─→ 带出处与双路排名信息的检索结果
    向量语义检索     ─┘

对上层（Agent 工具）只暴露 search()；同时保留 search_bm25_only / search_vector_only
两个方法，用于演示「单路 vs 混合」的命中差异。
"""

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from agent.rag.bm25 import BM25
from agent.rag.chunking import Chunk, load_chunks
from agent.rag.embedding import EmbeddingProvider, HashingEmbedding, build_embedding_provider
from agent.rag.hybrid import rrf_fuse
from agent.rag.tokenizer import tokenize
from agent.rag.vector_store import NumpyVectorStore

logger = logging.getLogger("HybridRetriever")


@dataclass
class RetrievedChunk:
    """一条检索结果：片段内容 + 融合得分 + 双路排名（便于溯源与效果分析）。"""

    chunk: Chunk
    score: float
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            **self.chunk.to_dict(),
            "score": round(self.score, 6),
            "bm25_rank": self.bm25_rank,
            "vector_rank": self.vector_rank,
        }


class HybridRetriever:
    """基于 BM25 + 向量检索与 RRF 融合的混合检索器。

    embedding_provider 为 None 时退化为「纯 BM25 关键词检索」单路模式：
    没有真实语义向量时，不该让无 IDF 的假向量参与融合去拉低结果质量。
    """

    def __init__(
        self,
        chunks: List[Chunk],
        embedding_provider: Optional[EmbeddingProvider] = None,
        top_k: int = 3,
        rrf_k: int = 60,
        candidate_k: int = 10,
        weights: Optional[List[float]] = None,
        min_score: float = 0.0,
    ):
        if not chunks:
            raise ValueError("知识库为空，无法构建检索器")

        self.chunks = chunks
        self.embedding_provider = embedding_provider
        self.top_k = top_k
        self.rrf_k = rrf_k
        # 每路先取回 candidate_k 条再融合，保证融合前有足够候选
        self.candidate_k = max(candidate_k, top_k)
        self.weights = weights
        # 向量相似度下限：低于该值的片段视为无关，不参与融合
        self.min_score = min_score

        self._index: Dict[str, Chunk] = {c.chunk_id: c for c in chunks}
        self.bm25 = BM25([tokenize(c.text) for c in chunks])

        self.vector_store: Optional[NumpyVectorStore] = None
        if embedding_provider is not None:
            self.vector_store = NumpyVectorStore()
            self.vector_store.add(
                [c.chunk_id for c in chunks],
                embedding_provider.embed([c.text for c in chunks]),
            )

    @property
    def has_vector_route(self) -> bool:
        """是否启用了向量检索路。"""
        return self.vector_store is not None

    # ---------- 单路检索 ----------

    def search_bm25_only(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        limit = top_k or self.top_k
        hits = self.bm25.search(query, top_k=limit)
        return [
            RetrievedChunk(chunk=self.chunks[index], score=score, bm25_rank=rank)
            for rank, (index, score) in enumerate(hits, start=1)
        ]

    def search_vector_only(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        if not self.has_vector_route:
            return []
        limit = top_k or self.top_k
        query_vector = self.embedding_provider.embed([query])[0]
        hits = self.vector_store.search(query_vector, top_k=limit, min_score=self.min_score)
        return [
            RetrievedChunk(chunk=self._index[chunk_id], score=score, vector_rank=rank)
            for rank, (chunk_id, score) in enumerate(hits, start=1)
        ]

    # ---------- 混合检索 ----------

    def search(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        """混合检索：两路召回 → RRF 融合 → 截断 top_k。

        无向量路时等价于纯 BM25 检索，但得分统一为 RRF 分，保证接口语义一致。
        """
        limit = top_k or self.top_k
        candidate_k = max(self.candidate_k, limit)

        bm25_hits = self.bm25.search(query, top_k=candidate_k)
        bm25_ranking = [self.chunks[index].chunk_id for index, _ in bm25_hits]
        bm25_positions = {cid: rank for rank, cid in enumerate(bm25_ranking, start=1)}

        rankings = [bm25_ranking]
        vector_positions: Dict[str, int] = {}
        if self.has_vector_route:
            query_vector = self.embedding_provider.embed([query])[0]
            vector_hits = self.vector_store.search(
                query_vector, top_k=candidate_k, min_score=self.min_score
            )
            vector_ranking = [chunk_id for chunk_id, _ in vector_hits]
            vector_positions = {cid: rank for rank, cid in enumerate(vector_ranking, start=1)}
            rankings.append(vector_ranking)

        fused = rrf_fuse(rankings, k=self.rrf_k, weights=self.weights)

        results: List[RetrievedChunk] = []
        for chunk_id, score in fused[:limit]:
            results.append(
                RetrievedChunk(
                    chunk=self._index[chunk_id],
                    score=score,
                    bm25_rank=bm25_positions.get(chunk_id),
                    vector_rank=vector_positions.get(chunk_id),
                )
            )
        return results


def build_retriever(config) -> HybridRetriever:
    """从配置构建检索器。

    读取 rag.knowledge_dir / chunk_size / chunk_overlap / top_k / rrf_k / candidate_k
    与 rag.embedding.* 配置。
    """
    knowledge_dir = config.get("rag.knowledge_dir", "agent/data/knowledge")
    if not os.path.isabs(knowledge_dir):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        knowledge_dir = os.path.join(project_root, knowledge_dir)

    chunks = load_chunks(
        knowledge_dir,
        chunk_size=config.get("rag.chunk_size", 300),
        overlap=config.get("rag.chunk_overlap", 50),
    )
    provider = build_embedding_provider(config)
    if isinstance(provider, HashingEmbedding):
        # 哈希向量不含语义信息、也没有 IDF，参与融合只会引入错误信号，
        # 因此这里主动禁用向量路，退化为纯 BM25 关键词检索。
        logger.warning(
            "未配置可用的 embedding 端点，检索退化为纯 BM25 关键词检索。"
            "如需语义召回，请配置 rag.embedding.base_url 与对应 API Key"
        )
        provider = None

    return HybridRetriever(
        chunks=chunks,
        embedding_provider=provider,
        top_k=config.get("rag.top_k", 3),
        rrf_k=config.get("rag.rrf_k", 60),
        candidate_k=config.get("rag.candidate_k", 10),
        min_score=config.get("rag.min_score", 0.0),
    )
