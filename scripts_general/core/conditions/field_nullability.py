"""
字段空/非空条件（token 级，通用）。

匹配 `X不为空` / `X为空`，X 为任意 case 字段名，如 `优惠券不为空`、`备注为空`。
判断依据：优先取 case 的 "{X}_数值"（>0 视为非空）；
无数值键时从原始值提取数字，无数字则按"非空字符串视为非空"处理。
"""

import re
from typing import Any, Dict

from core.conditions.atomic import AtomicCondition, safe_float

_PATTERN = re.compile(r"^(.+?)(不为空|为空)$")


def _numeric_value(case: Dict[str, Any], field: str) -> float:
    key = f"{field}_数值"
    if key in case:
        return safe_float(case[key])
    raw = case.get(field)
    if raw is None:
        return 0.0
    m = re.search(r"[\d.]+", str(raw))
    if m:
        return float(m.group())
    return 1.0 if str(raw).strip() else 0.0


class FieldNullabilityCondition(AtomicCondition):
    def match(self, s: str) -> bool:
        return bool(_PATTERN.match(s))

    def evaluate(self, s: str, case: Dict[str, Any]) -> bool:
        m = _PATTERN.match(s)
        if not m:
            return False
        field, op = m.group(1), m.group(2)
        val = _numeric_value(case, field)
        return (val > 0) if op == "不为空" else (val == 0)

    def describe(self, s: str) -> str:
        return s
