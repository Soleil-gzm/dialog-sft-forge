"""规则判定指标：对单个用例的运行结果打分（确定性，不调用 LLM）。

输入：ReActAgent.run() 返回的 result（含 answer / trace / truncated?）
      + 评测用例 EvalCase

七项指标（各 0~1）：
    tool_coverage     必调工具命中率；expected_order 全序命中加分；禁调工具命中记 0
    task_completion   产出答复 且 未截断 且 调用了 log_visit_result
    robustness        observations 解析后无 error 键的比例
    policy_citation   知识型用例：调用 search_knowledge_base 且答复含「依据：」
    no_fabrication    每个 action 均有 observation 回填的比例（规则近似）
    efficiency        步数效率：越接近 1 步越好

总分 = 加权平均；通过 = 总分 >= 0.7 且 task_completion == 1。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from agent.eval.case_schema import EvalCase

logger = logging.getLogger("EvalMetrics")

# 各指标权重（合计 1.0）
WEIGHTS = {
    "tool_coverage": 0.25,
    "task_completion": 0.25,
    "robustness": 0.15,
    "policy_citation": 0.15,
    "no_fabrication": 0.15,
    "efficiency": 0.05,
}

PASS_THRESHOLD = 0.7
CITATION_PATTERN = re.compile(r"依据[:：]")

# 执行级崩溃标记（tool_registry.execute 的确定性错误前缀）。
# 领域错误（如工具返回 {"error": "未找到会员: M9999"}）是工具的正常业务结果，
# 不应计为健壮性失败——否则「会员不存在」这类负向用例会被系统性扣分。
_EXEC_FAILURE_MARKERS = ("未注册的工具", "参数解析失败")


def _collect_actions(trace: List[Dict[str, Any]]) -> List[str]:
    """收集轨迹中所有已调用的工具名（保持调用顺序）。"""
    actions: List[str] = []
    for step in trace:
        actions.extend(step.get("actions") or [])
    return actions


def _has_error_observation(observations: List[Dict[str, Any]]) -> bool:
    """判断任意 observation 是否为执行级崩溃（解析后 error 命中崩溃标记）。

    注意：工具异常型失败（error 为任意异常文本）无法与领域错误可靠区分，
    此规则为近似实现，文档化其局限。
    """
    for obs in observations:
        raw = obs.get("result", "")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            msg = str(parsed.get("error", ""))
            if msg.startswith(_EXEC_FAILURE_MARKERS):
                return True
    return False


def evaluate_case(result: Dict[str, Any], case: EvalCase, max_steps: int = 6) -> Dict[str, Any]:
    """计算单个用例的指标明细。"""
    answer = (result.get("answer") or "").strip()
    trace = result.get("trace") or []
    truncated = bool(result.get("truncated"))
    actions = _collect_actions(trace)
    steps = len(trace)

    # ---- 1. 工具覆盖率 ----
    called = set(actions)
    expected_set = set(case.expected_tools)
    if set(case.must_not_call) & called:
        tool_coverage = 0.0  # 禁调工具被调用，直接记 0
    else:
        tool_coverage = len(expected_set & called) / len(expected_set) if expected_set else 0.0
        if case.expected_order:  # 期望顺序影响：满足 +0.1，不满足 -0.1（避免误用）
            it = iter(actions)
            order_ok = all(t in it for t in case.expected_order)
            if order_ok:
                tool_coverage = min(1.0, tool_coverage + 0.1)
            else:
                tool_coverage = max(0.0, tool_coverage - 0.1)

    # ---- 2. 任务完成 ----
    log_called = "log_visit_result" in called
    task_completion = 1.0 if (answer and not truncated and log_called) else 0.0

    # ---- 3. 工具健壮性 ----
    steps_with_obs = [s for s in trace if s.get("observations")]
    if steps_with_obs:
        error_steps = sum(1 for s in steps_with_obs if _has_error_observation(s["observations"]))
        robustness = 1.0 - error_steps / len(steps_with_obs)
    else:
        robustness = 1.0

    # ---- 4. 政策引用 ----
    if case.requires_knowledge:
        kb_called = "search_knowledge_base" in called
        has_citation = bool(CITATION_PATTERN.search(answer))
        policy_citation = 1.0 if (kb_called and has_citation) else 0.0
    else:
        policy_citation = 1.0  # 非知识型用例视为满足

    # ---- 5. 禁止编造（规则近似：每个 action 都有 observation 回填）----
    action_steps = [s for s in trace if s.get("actions")]
    if action_steps:
        filled = sum(
            1 for s in action_steps if len(s.get("observations") or []) >= len(s["actions"])
        )
        no_fabrication = filled / len(action_steps)
    else:
        no_fabrication = 1.0

    # ---- 6. 效率 ----
    if max_steps > 1:
        efficiency = max(0.0, 1.0 - (steps - 1) / (max_steps - 1))
    else:
        efficiency = 1.0

    metrics = {
        "tool_coverage": round(tool_coverage, 4),
        "task_completion": round(task_completion, 4),
        "robustness": round(robustness, 4),
        "policy_citation": round(policy_citation, 4),
        "no_fabrication": round(no_fabrication, 4),
        "efficiency": round(efficiency, 4),
    }
    total = sum(metrics[k] * w for k, w in WEIGHTS.items())
    total = round(total, 4)
    passed = total >= PASS_THRESHOLD and task_completion == 1.0

    return {
        "case_id": case.id,
        "passed": bool(passed),
        "total_score": total,
        "metrics": metrics,
        "steps": steps,
        "truncated": truncated,
        "actions": actions,
        "has_answer": bool(answer),
        "answer": answer,
    }
