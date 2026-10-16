"""RAG 检索层（零第三方依赖，仅使用标准库与 numpy）。

模块定位：为 Agent 提供「长期记忆」中的知识检索能力，也可独立于 Agent 单独使用。

组成：
    chunking     知识文档加载与分块（按章节切分 + 滑窗重叠）
    tokenizer    中英混合轻量分词（中文 bigram + unigram）
    bm25         BM25 关键词检索（手写打分公式）
    embedding    向量化 provider（API embedding / 离线哈希向量）
    vector_store 向量索引（numpy 暴力余弦，协议化便于替换为 FAISS）
    hybrid       RRF 融合排序（手写）
    retriever    混合检索统一入口 + 配置驱动构建
"""

from agent.rag.chunking import Chunk, load_chunks
from agent.rag.retriever import HybridRetriever, RetrievedChunk, build_retriever

__all__ = [
    "Chunk",
    "HybridRetriever",
    "RetrievedChunk",
    "build_retriever",
    "load_chunks",
]
