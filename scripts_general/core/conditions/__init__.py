"""
条件解析子包。

提供原子条件注册表 + 分词复合解析。
新增条件类型只需写一个 AtomicCondition 子类并 register。
"""

from .atomic import AtomicCondition, safe_float, safe_int
from .base import ConditionEvaluator
from .field_nullability import FieldNullabilityCondition
from .numeric_compare import NumericCompareCondition
from .parser import ConditionParser
from .passthrough import PassthroughCondition
from .unknown import UnknownTokenCondition

__all__ = [
    "ConditionEvaluator",
    "AtomicCondition",
    "ConditionParser",
    "PassthroughCondition",
    "NumericCompareCondition",
    "FieldNullabilityCondition",
    "UnknownTokenCondition",
    "safe_float",
    "safe_int",
]
