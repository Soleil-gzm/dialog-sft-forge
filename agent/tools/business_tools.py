"""奶茶店会员回访业务工具集。

6 个「任务规划型」工具（区别于纯话术生成，体现 Agent 的工具调用能力）：
    query_member_profile     查询会员画像
    query_purchase_history   查询消费记录
    check_inventory          查询商品库存
    calc_best_coupon         计算最优可用优惠
    generate_followup_text   生成回访话术（本地模板，不额外调用 LLM）
    log_visit_result         记录回访结果

数据源：agent/data/mock_data.json（完全虚构的奶茶店场景，可复现）
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.core.tool_registry import Tool, ToolRegistry

logger = logging.getLogger("BusinessTools")

_DATA_CACHE: Dict[str, Dict[str, Any]] = {}


def load_mock_data(path: str) -> Dict[str, Any]:
    """加载（并缓存）mock 数据，避免同一进程内重复读盘。"""
    if path not in _DATA_CACHE:
        with open(path, "r", encoding="utf-8") as f:
            _DATA_CACHE[path] = json.load(f)
    return _DATA_CACHE[path]


def _member_id_schema(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构造以 member_id 为必填参数的 JSON Schema。"""
    properties = {"member_id": {"type": "string", "description": "会员编号，如 M1001"}}
    required = ["member_id"]
    if extra:
        properties.update(extra)
        required.extend(extra.keys())
    return {"type": "object", "properties": properties, "required": required}


def build_registry(
    data_path: str,
    log_path: str = "",
    enabled: Optional[List[str]] = None,
) -> ToolRegistry:
    """构建工具注册表。

    Args:
        data_path: mock 数据文件路径
        log_path:  回访结果日志路径（log_visit_result 使用）
        enabled:   需要注册的工具名列表；为空则注册全部

    Returns:
        ToolRegistry 实例
    """
    data = load_mock_data(data_path)
    registry = ToolRegistry()
    visit_log_path = log_path or os.path.join(os.path.dirname(data_path), "visit_log.jsonl")

    # ---------- 1. 查询会员画像 ----------
    def query_member_profile(member_id: str) -> Dict[str, Any]:
        member = data.get("members", {}).get(member_id)
        if not member:
            return {"error": f"未找到会员: {member_id}"}
        return {"member_id": member_id, **member}

    # ---------- 2. 查询消费记录 ----------
    def query_purchase_history(member_id: str, limit: int = 3) -> Dict[str, Any]:
        records = data.get("purchase_history", {}).get(member_id, [])
        return {"member_id": member_id, "count": len(records), "records": records[-limit:]}

    # ---------- 3. 查询商品库存 ----------
    def check_inventory(product_name: str) -> Dict[str, Any]:
        item = data.get("inventory", {}).get(product_name)
        if not item:
            return {"error": f"未找到商品: {product_name}"}
        return {"product_name": product_name, **item}

    # ---------- 4. 计算最优优惠 ----------
    def calc_best_coupon(member_id: str) -> Dict[str, Any]:
        member = data.get("members", {}).get(member_id)
        if not member:
            return {"error": f"未找到会员: {member_id}"}
        level = member.get("level", "普通")
        coupons = data.get("coupons", {}).get(level, [])
        if not coupons:
            return {"member_id": member_id, "level": level, "coupon": None, "reason": "无可用优惠"}
        best = max(coupons, key=lambda c: c.get("discount", 0))
        return {"member_id": member_id, "level": level, "coupon": best, "candidates": coupons}

    # ---------- 5. 生成回访话术（本地模板） ----------
    def generate_followup_text(member_id: str, intent: str) -> Dict[str, Any]:
        member = data.get("members", {}).get(member_id)
        if not member:
            return {"error": f"未找到会员: {member_id}"}
        templates = data.get("followup_templates", {})
        template = templates.get(intent) or templates.get("默认")
        if not template:
            return {"error": f"未找到话术模板: {intent}"}
        return {"member_id": member_id, "intent": intent, "text": template.format(**member)}

    # ---------- 6. 记录回访结果 ----------
    def log_visit_result(member_id: str, outcome: str, note: str = "") -> Dict[str, Any]:
        record = {
            "member_id": member_id,
            "outcome": outcome,
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(visit_log_path), exist_ok=True)
        with open(visit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ok": True, "record": record, "file": visit_log_path}

    # ---------- 注册（JSON Schema 声明参数，供 LLM 决策） ----------
    registry.register(
        Tool(
            name="query_member_profile",
            description="查询会员基础画像：姓名、等级、积分、积分到期日、联系方式。回访第一步应调用。",
            parameters=_member_id_schema(),
            func=query_member_profile,
        )
    )
    registry.register(
        Tool(
            name="query_purchase_history",
            description="查询会员最近的消费记录（商品、金额、日期），用于了解偏好与消费能力。",
            parameters=_member_id_schema(
                {"limit": {"type": "integer", "description": "返回最近几条记录，默认 3"}}
            ),
            func=query_purchase_history,
        )
    )
    registry.register(
        Tool(
            name="check_inventory",
            description="查询指定商品的当前库存与状态，推荐商品前必须确认有货。",
            parameters={
                "type": "object",
                "properties": {
                    "product_name": {"type": "string", "description": "商品名称，如 茉莉奶绿"}
                },
                "required": ["product_name"],
            },
            func=check_inventory,
        )
    )
    registry.register(
        Tool(
            name="calc_best_coupon",
            description="根据会员等级计算当前可用的最优优惠券，涉及推荐优惠时应先调用，禁止自行编造优惠。",
            parameters=_member_id_schema(),
            func=calc_best_coupon,
        )
    )
    registry.register(
        Tool(
            name="generate_followup_text",
            description="按回访意图生成一段回访话术文本。intent 取值：积分到期提醒 / 活动推荐 / 流失挽回 / 默认。",
            parameters=_member_id_schema(
                {"intent": {"type": "string", "description": "回访意图，如 积分到期提醒"}}
            ),
            func=generate_followup_text,
        )
    )
    registry.register(
        Tool(
            name="log_visit_result",
            description="记录本次回访结果，任务结束前必须调用一次。",
            parameters=_member_id_schema(
                {
                    "outcome": {"type": "string", "description": "回访结果，如 已触达 / 未接听 / 明确拒绝"},
                    "note": {"type": "string", "description": "备注信息，可选"},
                }
            ),
            func=log_visit_result,
        )
    )

    # enabled 为空则全部启用；否则只保留启用的工具（重建注册表）
    if enabled:
        filtered = ToolRegistry()
        for name in enabled:
            if name in registry.names():
                filtered.register(registry.get(name))
        return filtered

    return registry
