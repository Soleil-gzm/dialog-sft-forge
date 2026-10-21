"""生成器 output（case + prompt + messages）→ EvalCase 的转换（纯函数）。

把生成器产出的业务场景转换成 Agent 评测用例：
  - 首条 user 消息 → task（Agent 的输入任务文本）
  - case 字段 / prompt 文本 / 消息内容 → expected_tools（期望工具序列）与 requires_knowledge
  - case 字段 → acceptance（人工核对用的验收点，不计分）

规则为启发式关键词匹配，供「生成越多→评测越广」的批量回流使用；准确率
不追求 100%，误差可通过最终评测结果暴露。所有函数保持纯函数，便于单测。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from agent.eval.case_schema import EvalCase

logger = logging.getLogger("BackflowConvert")

# 触发 → 期望工具 的规则权重表（顺序无关，命中即叠加）
_TOOL_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("优惠券", "满减", "抵扣", "会员日", "第二杯半价", "满 2", "满 3", "立减"), "calc_best_coupon"),
    (("积分", "到期", "清零", "积分余额"), "query_member_profile"),
    (("饮品", "商品", "口味", "库存", "缺货", "推荐", "新品", "奶绿", "珍珠", "桂花", "芝士"), "check_inventory"),
    (("配送", "退款", "投诉", "免运费", "售后", "满 消费金额折免运费"), "search_knowledge_base"),
    (("历史", "之前", "上次", "最近一次", "回归"), "recall_member_history"),
]

# 触发 → requires_knowledge 的关键词
_KNOWLEDGE_TRIGGERS = (
    "积分能怎么用", "积分规则", "优惠规则", "怎么抵扣", "配送", "退款",
    "会员日", "政策", "制度", "多少积分", "权益", "如何", "能不能",
)

_ENV_LITERALS = (
    "会员日", "本周", "活动", "满 消费金额元", "到期", "积分兑换",
)


def messages_to_task(messages: List[Dict[str, str]], case: Dict[str, Any]) -> str:
    """任务文本：用 case 字段合成自包含任务（含等级/积分/目标），
    客户端开场（首条 user）仅作参考，避免生出寒暄式短任务导致 Agent 缺信息。"""
    name = _text(case, "客户姓名") or "该会员"
    level = _text(case, "会员等级") or "会员"
    points = _text(case, "积分余额") or "有积分"
    coupon = _text(case, "优惠券")
    first_user = _first_user_content(messages)
    base = (
        f"对{level}会员{name}（{points}分）做一次会员回访，"
        f"告知积分/优惠情况并引导到店，结束时记录回访结果。"
    )
    if coupon:
        base = base.replace("做一次会员回访", f"做一次会员回访（其账户有 {coupon}）")
    if first_user:
        base += f" 客户开场说：“{first_user}”"
    return base


def derive_expected_tools(
    case: Dict[str, Any],
    prompt_text: str,
    messages: List[Dict[str, str]],
) -> Tuple[List[str], bool]:
    """返回 (expected_tools 去重保序列表, requires_knowledge)。"""
    text = build_text(case, prompt_text, messages)

    tools: List[str] = []
    for words, tool in _TOOL_RULES:
        if any(w in text for w in words):
            if tool not in tools:
                tools.append(tool)

    # 涉及政策 / 积分规则解释时置 knowledge，但仅当知识库命中（需调 search_knowledge_base）
    requires_knowledge = any(k in text for k in _KNOWLEDGE_TRIGGERS)

    # 环境字面量里若包含明确的优惠券/会员日字眼，确保 calc_best_coupon 不被漏掉
    if requires_knowledge and "calc_best_coupon" not in tools and any(k in text for k in _ENV_LITERALS):
        tools.append("calc_best_coupon")

    # 知识型用例必须真正检索知识库（metrics.policy_citation 要求 kb_called 且答复带出处）
    if requires_knowledge and "search_knowledge_base" not in tools:
        tools.append("search_knowledge_base")

    # 回访任务一律收尾 log_visit_result
    if "log_visit_result" not in tools:
        tools.append("log_visit_result")

    return tools, requires_knowledge


def build_text(case: Dict[str, Any], prompt_text: str, messages: List[Dict[str, str]]) -> str:
    parts: List[str] = []
    if message := _first_user_content(messages):
        parts.append(message)
    if prompt_text:
        parts.append(_strip_placeholders(prompt_text))
    for k, v in (case or {}).items():
        if isinstance(v, (str, int, float)):
            parts.append(f"{k}:{v}")
    return " ".join(parts)


def derive_acceptance(case: Dict[str, Any], prompt_text: str, messages: List[Dict[str, str]]) -> List[str]:
    """按关键词映射人类可读验收点（仅备注，metrics 不消费 acceptance）。"""
    text = _strip_placeholders(build_text(case, prompt_text, messages))
    acc: List[str] = []
    if any(k in text for k in ("优惠券", "满减", "抵扣", "会员日")):
        acc.append("答复应说明适用优惠与如何叠加")
    if any(k in text for k in ("积分", "到期", "清零")):
        acc.append("答复应说明积分余额与到期风险")
    if any(k in text for k in ("配送", "退款", "投诉")):
        acc.append("答复应说明服务政策并标注出处")
    if any(k in text for k in ("饮品", "商品", "推荐", "缺货")):
        acc.append("推荐/答复应基于真实的消费记录与库存")
    return acc or ["完成一次礼貌、信息准确的会员回访"]


def to_eval_case(
    case_id: str,
    member_id: str,
    case: Dict[str, Any],
    prompt_text: str,
    messages: List[Dict[str, str]],
) -> EvalCase:
    """组装 dict 后用 EvalCase.from_dict 做字段白名单/必填校验。"""
    task = messages_to_task(messages, case) or _text(case, "客户姓名")
    expected_tools, requires_knowledge = derive_expected_tools(case, prompt_text, messages)
    raw = {
        "id": case_id,
        "member_id": member_id,
        "task": task,
        "expected_tools": expected_tools,
        "requires_knowledge": requires_knowledge,
        "acceptance": derive_acceptance(case, prompt_text, messages),
    }
    return EvalCase.from_dict(raw)


# ---------------- 内部小工具 ----------------

def _text(case: Dict[str, Any], key: str) -> str:
    return str(case.get(key) or "").strip()


def _first_user_content(messages: List[Dict[str, str]]) -> str:
    for msg in messages or []:
        if msg.get("role") == "user" and str(msg.get("content") or "").strip():
            return str(msg["content"]).strip()
    return ""


def _strip_placeholders(text: str) -> str:
    """去除 {占位符}，避免把字段名当关键词触发规则。"""
    import re

    return re.sub(r"\{[^}]*\}", "", text or "")