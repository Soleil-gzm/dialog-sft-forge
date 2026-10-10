"""
数值比较条件（token 级，通用）。

匹配 `{字段}(小于|等于|大于)N`，如 `{积分余额}大于1000`、`{次数}等于5`。
取值优先级：case 的 "{字段}_数值"（由数据加载器自动附加）→ 直接解析 case[字段] 中的数字。
"""

import re
from typing import Any, Dict

from core.conditions.atomic import AtomicCondition, safe_float

_PATTERN = re.compile(r"^\{(.+)\}(小于|等于|大于)(\d+)$")


def _numeric_value(case: Dict[str, Any], field: str) -> float:
    """优先取 {字段}_数值，否则从原始值中提取数字"""
    key = f"{field}_数值"
    if key in case:
        return safe_float(case[key])
    raw = case.get(field)
    if raw is None:
        return 0.0
    m = re.search(r"[\d.]+", str(raw))
    return float(m.group()) if m else 0.0


class NumericCompareCondition(AtomicCondition):
    def match(self, s: str) -> bool:
        return bool(_PATTERN.match(s))

    def evaluate(self, s: str, case: Dict[str, Any]) -> bool:
        m = _PATTERN.match(s)
        if not m:
            return False
        field, op, threshold_str = m.group(1), m.group(2), m.group(3)
        try:
            threshold = int(threshold_str)
        except ValueError:
            return False
        value = _numeric_value(case, field)
        if op == "小于":
            return value < threshold
        if op == "等于":
            return value == threshold
        if op == "大于":
            return value > threshold
        return False

    def describe(self, s: str) -> str:
        return s
