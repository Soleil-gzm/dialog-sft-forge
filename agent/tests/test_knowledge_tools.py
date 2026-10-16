"""知识检索类工具测试（离线，不依赖网络与 LLM）。

覆盖：
  - 注册行为：无检索器时只注册 6 个业务工具；有检索器时追加 2 个知识工具
  - search_knowledge_base：返回片段与出处、无命中时的降级提示
  - recall_member_history：按会员过滤、最近的在前、limit、无日志文件、坏行跳过
  - enabled 过滤对知识工具同样生效
"""

import json
import os
import sys

import pytest

# agent/tests/test_knowledge_tools.py -> 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.rag.chunking import load_chunks  # noqa: E402
from agent.rag.retriever import HybridRetriever  # noqa: E402
from agent.tools.business_tools import build_registry  # noqa: E402

KNOWLEDGE_DIR = os.path.join(PROJECT_ROOT, "agent", "data", "knowledge")
MOCK_DATA = os.path.join(PROJECT_ROOT, "agent", "data", "mock_data.json")

BUSINESS_TOOLS = {
    "query_member_profile",
    "query_purchase_history",
    "check_inventory",
    "calc_best_coupon",
    "generate_followup_text",
    "log_visit_result",
}
KNOWLEDGE_TOOLS = {"search_knowledge_base", "recall_member_history"}


@pytest.fixture(scope="module")
def retriever():
    """与生产默认一致：无 embedding 端点时走纯 BM25 单路检索。"""
    chunks = load_chunks(KNOWLEDGE_DIR)
    return HybridRetriever(chunks, embedding_provider=None, top_k=3)


@pytest.fixture
def log_file(tmp_path):
    """构造一份含空行与坏行的回访日志。"""
    path = tmp_path / "visit_log.jsonl"
    records = [
        {"member_id": "M1001", "outcome": "已触达", "note": "第一次回访", "timestamp": "2026-10-01T00:00:00+00:00"},
        {"member_id": "M1002", "outcome": "未接听", "note": "其他会员记录", "timestamp": "2026-10-02T00:00:00+00:00"},
        {"member_id": "M1001", "outcome": "已触达", "note": "第二次回访", "timestamp": "2026-10-05T00:00:00+00:00"},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.write("\n")
        f.write("{ 这不是合法 JSON\n")
    return str(path)


def _call(registry, tool, **kwargs):
    return json.loads(registry.execute(tool, json.dumps(kwargs, ensure_ascii=False)))


# ---------------- 注册行为 ----------------


def test_without_retriever_only_business_tools():
    registry = build_registry(MOCK_DATA)
    assert set(registry.names()) == BUSINESS_TOOLS


def test_with_retriever_registers_knowledge_tools(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    assert set(registry.names()) == BUSINESS_TOOLS | KNOWLEDGE_TOOLS


def test_enabled_filter_applies_to_knowledge_tools(retriever, log_file):
    registry = build_registry(
        MOCK_DATA,
        log_path=log_file,
        enabled=["query_member_profile", "search_knowledge_base"],
        retriever=retriever,
    )
    assert set(registry.names()) == {"query_member_profile", "search_knowledge_base"}


def test_knowledge_tool_schema_is_openai_compatible(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    schemas = {s["function"]["name"]: s for s in registry.schemas(list(KNOWLEDGE_TOOLS))}
    assert schemas["search_knowledge_base"]["function"]["parameters"]["required"] == ["query"]
    assert schemas["recall_member_history"]["function"]["parameters"]["required"] == ["member_id"]


# ---------------- search_knowledge_base ----------------


def test_search_knowledge_base_returns_citation(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    result = _call(registry, "search_knowledge_base", query="积分什么时候过期")

    assert result["count"] > 0
    first = result["results"][0]
    assert first["citation"]
    assert first["source"].startswith("knowledge/")
    assert "points.md" in first["source"]
    assert first["text"]


def test_search_knowledge_base_respects_top_k(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    result = _call(registry, "search_knowledge_base", query="优惠券规则", top_k=1)
    assert result["count"] == 1


def test_search_knowledge_base_no_hit(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    result = _call(registry, "search_knowledge_base", query="巧克力慕斯蛋糕")

    assert result["count"] == 0
    assert result["results"] == []
    assert "未找到" in result["note"]


# ---------------- recall_member_history ----------------


def test_recall_member_history_filters_and_orders(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    result = _call(registry, "recall_member_history", member_id="M1001")

    assert result["count"] == 2
    assert all(r["member_id"] == "M1001" for r in result["records"])
    assert result["records"][0]["note"] == "第二次回访"  # 最近的记录在最前


def test_recall_member_history_limit(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    result = _call(registry, "recall_member_history", member_id="M1001", limit=1)
    assert result["count"] == 1


def test_recall_member_history_unknown_member(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    result = _call(registry, "recall_member_history", member_id="M9999")
    assert result["count"] == 0
    assert "无历史回访记录" in result["note"]


def test_recall_member_history_missing_file(retriever, tmp_path):
    registry = build_registry(
        MOCK_DATA, log_path=str(tmp_path / "not_exist.jsonl"), retriever=retriever
    )
    result = _call(registry, "recall_member_history", member_id="M1001")
    assert result["count"] == 0


def test_recall_member_history_skips_malformed_lines(retriever, log_file):
    registry = build_registry(MOCK_DATA, log_path=log_file, retriever=retriever)
    # 日志含空行与坏行，仍应正常返回有效记录
    assert _call(registry, "recall_member_history", member_id="M1002")["count"] == 1
