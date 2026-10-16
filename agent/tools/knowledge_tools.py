"""知识检索类工具 —— 把 RAG 检索层接入 Agent 的长期记忆能力。

两个工具（在 M1 的 6 个业务工具之外新增）：
    search_knowledge_base    检索奶茶店知识库（会员政策 / 积分 / 优惠券 / 服务），返回片段与出处
    recall_member_history    召回该会员的历史回访记录，实现跨会话记忆

设计说明：
- 历史回访记录带明确的 member_id 键，采用结构化过滤而非语义检索，
  避免语义检索把其他会员的记录误召回；
- 检索结果自带 citation，Agent 需在答复中标注依据，实现 RAG 溯源。
"""

import json
import logging
import os
from typing import Any, Dict, List

from agent.core.tool_registry import Tool, ToolRegistry

logger = logging.getLogger("KnowledgeTools")


def _read_member_history(log_path: str, member_id: str, limit: int) -> List[Dict[str, Any]]:
    """从回访日志中筛选指定会员的记录，最近的在最前。"""
    if not log_path or not os.path.isfile(log_path):
        return []

    records: List[Dict[str, Any]] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("member_id") == member_id:
                records.append(record)
    return records[-limit:][::-1]


def register_knowledge_tools(registry: ToolRegistry, retriever, log_path: str = "") -> None:
    """把知识检索工具注册进注册表；retriever 为 None 时跳过（不引入硬依赖）。"""
    if retriever is None:
        return

    def search_knowledge_base(query: str, top_k: int = 3) -> Dict[str, Any]:
        results = retriever.search(query, top_k=top_k)
        if not results:
            return {
                "query": query,
                "count": 0,
                "results": [],
                "note": "知识库中未找到相关条目，请勿凭空作答",
            }
        return {
            "query": query,
            "count": len(results),
            "results": [item.to_dict() for item in results],
        }

    def recall_member_history(member_id: str, limit: int = 3) -> Dict[str, Any]:
        records = _read_member_history(log_path, member_id, limit)
        return {
            "member_id": member_id,
            "count": len(records),
            "records": records,
            "note": "无历史回访记录" if not records else "最近的记录在最前",
        }

    registry.register(
        Tool(
            name="search_knowledge_base",
            description=(
                "检索奶茶店知识库，用于回答会员政策、积分规则、优惠券使用、配送与售后等知识性问题。"
                "凡涉及政策与规则的内容都必须先检索，禁止凭记忆作答。返回结果含出处（citation）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题，如 积分什么时候过期"},
                    "top_k": {"type": "integer", "description": "返回片段数，默认 3"},
                },
                "required": ["query"],
            },
            func=search_knowledge_base,
        )
    )
    registry.register(
        Tool(
            name="recall_member_history",
            description=(
                "召回该会员的历史回访记录（时间、结果、备注），用于了解上次沟通情况，"
                "避免重复打扰或做出重复承诺。回访开始时应调用一次。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "member_id": {"type": "string", "description": "会员编号，如 M1001"},
                    "limit": {"type": "integer", "description": "返回最近几条记录，默认 3"},
                },
                "required": ["member_id"],
            },
            func=recall_member_history,
        )
    )
