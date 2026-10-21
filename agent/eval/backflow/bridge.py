"""生成器身份 → Agent 运行时会员身份 的桥接。

生成器 case（如 case_0001.txt 的 {客户姓名/会员等级/积分余额/优惠券/到期日期}）
与 Agent 环境 mock_data.json 的成员 schema（name/gender/level/points/points_expire/...）
字段不同。M5 回流时不再复用现有 member_id（M1001-M1004），而是为每个回流场景
生成一个新的运行时会员编号（如 BF0001），并把 case 字段映射到成员 schema 字段，
做到 1:1 忠实，避免复用现有成员导致话术与数据冲突、评测失真。

本模块为纯函数 + 轻量占位符归一化，服务于 seed.py（运行时注入）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def member_id_for_case(index: int) -> str:
    """按序号生成回流会员编号，如 index=1 -> BF0001。"""
    return f"BF{index:04d}"


def _norm_name(value: Any) -> str:
    return str(value or "").strip()


def map_fields(case: Dict[str, Any]) -> Dict[str, Any]:
    """把生成器 case 字段映射为 Agent 成员 schema 字段。"""
    name = _norm_name(case.get("客户姓名"))
    is_female = "女士" in (_norm_name(case.get("客户性别")) or "先生")
    return {
        "name": name,
        "gender": "女士" if is_female else "先生",
        "level": _norm_name(case.get("会员等级")) or "普通",
        "points": _to_int(case.get("积分余额")),
        "points_expire": _to_date(_norm_name(case.get("到期日期"))),
        "last_purchase_amount": _extract_amount(_norm_name(case.get("消费金额"))),
        "phone": f"199****{_index_str(name)}" if name else "",
        "register_date": "2025-01-01",
    }


def _to_int(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value or ""))
    return int(m.group()) if m else 0


def _extract_amount(value: str) -> int:
    """从 "49元" 提取 49；empty -> 0。"""
    if value == "":
        return 0
    m = re.search(r"\d+", value)
    return int(m.group()) if m else 0


def _to_date(value: str) -> str:
    """把 "2027年5月2日" / "2026年5月2日" 归一化为 ISO 日期（YYYY-MM-DD）。"""
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value)
    if not m:
        return "2027-01-01"
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _index_str(name: str) -> str:
    """从名字生成后四位，用于电话占位，保证基本唯一。"""
    return f"{sum(ord(c) for c in name) % 10000:04d}"


def synthesize_purchase_history(case: Dict[str, Any], member_id: str) -> List[Dict[str, Any]]:
    """兜底生成 1 条消费记录（供 query_purchase_history 返回非空）。"""
    amounts = {
        "银卡": 49, "金卡": 58, "VIP": 68, "普通": 20,
    }
    products = ["珍珠奶茶", "茉莉奶绿", "芝士葡萄", "桂花乌龙", "杨枝甘露"]
    idx = sum(ord(c) for c in member_id) % len(products)
    return [
        {
            "date": "2026-09-01",
            "product": products[idx],
            "amount": amounts.get(str(case.get("会员等级") or "").strip(), 20),
        }
    ]


def coupon_for_level(level: str) -> List[Dict[str, Any]]:
    """为回流会员等级生成一组券（运行时注入 coupons 桶，映射到现有类别）。"""
    level = str(level or "").strip()
    if level == "VIP":
        return [
            {"name": "满 35 减 10", "threshold": 35, "discount": 10},
            {"name": "满 48 减 15", "threshold": 48, "discount": 15},
        ]
    if level == "金卡":
        return [
            {"name": "满 30 减 8", "threshold": 30, "discount": 8},
            {"name": "满 45 减 12", "threshold": 45, "discount": 12},
        ]
    if level == "银卡":
        return [
            {"name": "满 25 减 6", "threshold": 25, "discount": 6},
            {"name": "满 40 减 10", "threshold": 40, "discount": 10},
        ]
    return [
        {"name": "满 20 减 5", "threshold": 20, "discount": 5},
        {"name": "第二杯半价", "threshold": 0, "discount": 0},
    ]