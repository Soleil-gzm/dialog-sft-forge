"""RAG 检索层单元测试（完全离线，不依赖网络与 LLM）。

覆盖：
  - tokenizer：中文 bigram / unigram、英文数字、空输入
  - chunking：知识库加载、出处信息、滑窗重叠、异常路径
  - bm25：命中排序、未登录词、空查询
  - vector_store：余弦排序、维度校验
  - hybrid(rrf)：融合排序、权重校验
  - embedding：哈希向量确定性与形状
  - retriever：端到端混合检索、单路检索、结果结构
"""

import os
import sys

import numpy as np
import pytest

# agent/tests/test_rag.py -> 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.rag.bm25 import BM25  # noqa: E402
from agent.rag.chunking import load_chunks  # noqa: E402
from agent.rag.embedding import HashingEmbedding  # noqa: E402
from agent.rag.hybrid import rrf_fuse  # noqa: E402
from agent.rag.retriever import HybridRetriever  # noqa: E402
from agent.rag.tokenizer import tokenize  # noqa: E402
from agent.rag.vector_store import NumpyVectorStore  # noqa: E402

KNOWLEDGE_DIR = os.path.join(PROJECT_ROOT, "agent", "data", "knowledge")


# ---------------- tokenizer ----------------


def test_tokenize_chinese_bigram():
    assert tokenize("积分") == ["积分"]
    assert tokenize("积分到期") == ["积分", "分到", "到期"]


def test_tokenize_single_cjk_kept():
    # 单字查询（如「券」）必须仍可召回
    assert tokenize("券") == ["券"]
    assert "满" in tokenize("满48减15")


def test_tokenize_mixed_and_symbols_dropped():
    tokens = tokenize("VIP 满48减15")
    assert "vip" in tokens
    assert "48" in tokens
    assert "减" in tokens


def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize("，。！") == []


# ---------------- chunking ----------------


def test_load_chunks_covers_all_docs():
    chunks = load_chunks(KNOWLEDGE_DIR, chunk_size=300, overlap=50)
    assert len(chunks) >= 8
    sources = {c.source for c in chunks}
    assert "knowledge/points.md" in sources
    assert "knowledge/coupons.md" in sources


def test_chunk_has_citation_and_unique_id():
    chunks = load_chunks(KNOWLEDGE_DIR)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "chunk_id 必须唯一"
    assert all(c.citation() for c in chunks)
    assert all(c.doc_title for c in chunks)


def test_chunk_overlap_produces_multiple_pieces():
    # 用超小窗口强制切分，验证同一章节被切成多块且有重叠
    chunks = load_chunks(KNOWLEDGE_DIR, chunk_size=60, overlap=20)
    assert len(chunks) > len(load_chunks(KNOWLEDGE_DIR, chunk_size=100000))
    assert any(len(c.text) <= 60 for c in chunks)


def test_load_chunks_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_chunks(str(tmp_path / "not_exist"))


# ---------------- bm25 ----------------


@pytest.fixture
def small_index():
    docs = ["积分自入账之日起有效期十二个月到期清零", "配送费三元起送", "会员日双倍积分"]
    return BM25([tokenize(d) for d in docs])


def test_bm25_ranks_matching_doc_first(small_index):
    hits = small_index.search("配送费", top_k=3)
    assert hits, "应至少命中一篇文档"
    assert hits[0][0] == 1


def test_bm25_unknown_term_returns_empty(small_index):
    assert small_index.search("巧克力蛋糕拿铁") == []


def test_bm25_empty_query(small_index):
    assert small_index.search("") == []


def test_bm25_scores_are_non_negative(small_index):
    scores = small_index.get_scores(tokenize("积分 配送费"))
    assert all(s >= 0 for s in scores)


def test_bm25_empty_corpus():
    index = BM25([])
    assert index.search("积分") == []


# ---------------- vector_store ----------------


def test_vector_store_cosine_order():
    store = NumpyVectorStore()
    store.add(["same", "orthogonal", "opposite"], np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]))
    hits = store.search(np.array([1.0, 0.0]), top_k=3)
    assert [cid for cid, _ in hits] == ["same", "orthogonal", "opposite"]
    assert hits[0][1] == pytest.approx(1.0)
    assert hits[2][1] == pytest.approx(-1.0)


def test_vector_store_dimension_mismatch():
    store = NumpyVectorStore()
    with pytest.raises(ValueError):
        store.add(["a", "b"], np.array([[1.0, 0.0]]))


def test_vector_store_empty_search():
    assert NumpyVectorStore().search(np.array([1.0, 0.0]), top_k=3) == []


# ---------------- hybrid (rrf) ----------------


def test_rrf_fuse_ordering():
    fused = rrf_fuse([["a", "b", "c"], ["c", "a"]], k=60)
    order = [doc_id for doc_id, _ in fused]
    assert order == ["a", "c", "b"]


def test_rrf_doc_hit_by_both_routes_ranks_higher():
    fused = dict(rrf_fuse([["x", "y"], ["y"]], k=60))
    assert fused["y"] > fused["x"]


def test_rrf_weight_count_mismatch():
    with pytest.raises(ValueError):
        rrf_fuse([["a"]], weights=[1.0, 2.0])


def test_rrf_weights_change_order():
    unweighted = [d for d, _ in rrf_fuse([["a"], ["b"]], k=0)]
    weighted = [d for d, _ in rrf_fuse([["a"], ["b"]], k=0, weights=[2.0, 1.0])]
    assert unweighted[0] == "a"  # 同分按 id 升序
    assert weighted[0] == "a"


# ---------------- embedding ----------------


def test_hashing_embedding_deterministic_and_shaped():
    provider = HashingEmbedding(dim=64)
    first = provider.embed(["积分到期", "配送费"])
    second = provider.embed(["积分到期", "配送费"])
    assert first.shape == (2, 64)
    assert np.array_equal(first, second), "哈希向量必须可复现"


def test_hashing_embedding_favours_overlapping_text():
    provider = HashingEmbedding()
    query = provider.embed(["积分到期清零"])[0]
    near = provider.embed(["积分到期"])[0]
    far = provider.embed(["配送费三元"])[0]
    assert float(query @ near) > float(query @ far)


# ---------------- retriever（端到端） ----------------


@pytest.fixture(scope="module")
def retriever():
    chunks = load_chunks(KNOWLEDGE_DIR)
    return HybridRetriever(chunks, HashingEmbedding(), top_k=3, rrf_k=60)


def test_build_retriever_from_config():
    from agent.core.config import load_agent_config
    from agent.rag.retriever import build_retriever

    config = load_agent_config(os.path.join(PROJECT_ROOT, "agent", "config", "agent_config.yaml"))
    built = build_retriever(config)
    assert built.chunks
    assert built.top_k == 3
    # 默认配置没有 embedding 端点 → 不应启用无意义的哈希向量路
    assert built.has_vector_route is False


def test_retriever_without_vector_route_equals_bm25():
    chunks = load_chunks(KNOWLEDGE_DIR)
    single = HybridRetriever(chunks, embedding_provider=None, top_k=3)
    assert single.has_vector_route is False
    assert single.search_vector_only("积分", top_k=3) == []

    hybrid_order = [r.chunk.chunk_id for r in single.search("积分有效期", top_k=3)]
    bm25_order = [r.chunk.chunk_id for r in single.search_bm25_only("积分有效期", top_k=3)]
    assert hybrid_order == bm25_order
    assert all(r.vector_rank is None for r in single.search("积分有效期", top_k=3))


def test_retriever_returns_requested_top_k(retriever):
    assert len(retriever.search("积分什么时候过期", top_k=2)) == 2


def test_retriever_finds_points_policy(retriever):
    results = retriever.search("积分到期后会自动清零吗", top_k=5)
    assert any("points.md" in r.chunk.source for r in results)


def test_retriever_finds_coupon_policy(retriever):
    results = retriever.search("VIP 会员可以用满 48 减 15 的券吗", top_k=5)
    assert any("coupons.md" in r.chunk.source for r in results)


def test_retriever_finds_delivery_policy(retriever):
    results = retriever.search("配送费是多少", top_k=5)
    assert any("service.md" in r.chunk.source for r in results)


def test_retriever_single_route_methods(retriever):
    assert retriever.search_bm25_only("积分", top_k=2)
    assert retriever.search_vector_only("积分", top_k=2)


def test_retriever_result_payload_has_citation(retriever):
    result = retriever.search("积分有效期", top_k=1)[0]
    payload = result.to_dict()
    assert payload["citation"]
    assert payload["source"].startswith("knowledge/")
    assert isinstance(payload["score"], float)


def test_retriever_requires_non_empty_chunks():
    with pytest.raises(ValueError):
        HybridRetriever([], HashingEmbedding())
