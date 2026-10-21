"""运行时注入回流会员到 Agent 环境（零改盘）。

利用 agent/tools/business_tools.py 的 load_mock_data(path) 按路径缓存同一
可变 dict 的机制：先 load_mock_data(data_path) 拿到 dict，再就地写入新会员
members[member_id]、coupons 桶、purchase_history[member_id]。之后 build_registry
与 run_eval 内部再次 load_mock_data 会命中缓存，工具闭包即可读到注入数据，
且磁盘 mock_data.json 字节不变。

注意：calc_best_coupon 按 member['level'] 读取 data['coupons'][level]（见
business_tools.py L95-96），因此必须为回流会员的等级补一个 coupons 桶，否则无
可用优惠。search_knowledge_base 走 RAG 读知识库 md，与 level 无关，无需处理。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from agent.tools.business_tools import load_mock_data

from .bridge import coupons_from_case, map_fields, member_id_for_case, synthesize_purchase_history

logger = logging.getLogger("BackflowSeed")

_SENTINEL = object()


def ensure_member(
    data_path: str,
    member_id: str,
    case: Dict[str, Any],
    coupons: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 case 注入为运行时会员，返回注入后的 member dict。幂等：重复调用不报错。

    若指定 coupons（本题库映射后的券桶表），则一并补到 data['coupons']，
    覆盖 coupon_for_level 的默认券。
    """
    data = load_mock_data(data_path)

    members = data.setdefault("members", {})
    if member_id in members:
        return members[member_id]

    member = map_fields(case)
    members[member_id] = member

    level = member["level"]
    # 级别桶作兜底（保持与现有 mock 结构一致）
    data.setdefault("coupons", {}).setdefault(level, coupons_from_case({"优惠券": ""}, level))
    # 会员级券：优先取案例里真实写明的券，供 calc_best_coupon 使用
    member_coupons = coupons if coupons is not None else coupons_from_case(case, level)
    data.setdefault("member_coupons", {})[member_id] = member_coupons

    history = data.setdefault("purchase_history", {})
    if member_id not in history:
        history[member_id] = synthesize_purchase_history(case, member_id)

    return member


def inject_for_case(
    data_path: str,
    index: int,
    case: Dict[str, Any],
    coupons: Optional[Dict[str, Any]] = None,
) -> str:
    """便捷入口：注入并返回 member_id（如 BF0001）。"""
    member_id = member_id_for_case(index)
    ensure_member(data_path, member_id, case, coupons=coupons)
    return member_id