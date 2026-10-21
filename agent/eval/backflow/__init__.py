"""M5 生成器→Agent 评测集回流 子模块。"""

from .bridge import member_id_for_case, map_fields, synthesize_purchase_history
from .convert import (
    to_eval_case,
    derive_expected_tools,
    derive_acceptance,
    messages_to_task,
    build_text,
)
from .seed import inject_for_case, ensure_member

__all__ = [
    "member_id_for_case",
    "map_fields",
    "synthesize_purchase_history",
    "to_eval_case",
    "derive_expected_tools",
    "derive_acceptance",
    "messages_to_task",
    "build_text",
    "inject_for_case",
    "ensure_member",
]