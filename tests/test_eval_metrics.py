"""规则指标测试：覆盖全命中/缺调/顺序/禁调/截断/工具错误/编造/引用/效率。"""

import json

from agent.eval.case_schema import EvalCase
from agent.eval.metrics import WEIGHTS, evaluate_case


def _obs(tool_name: str, payload: dict) -> list:
    return [{"tool": tool_name, "result": json.dumps(payload, ensure_ascii=False)}]


def _result(step_actions, observations=None, answer="ok", truncated=False):
    """构造 ReActAgent.run 返回结构。step_actions: 每步的工具名列表。"""
    trace = []
    observations = observations or []
    for i, actions in enumerate(step_actions, 1):
        step = {"step": i, "thought": "思考", "actions": actions}
        if i - 1 < len(observations) and observations[i - 1]:
            step["observations"] = observations[i - 1]
        trace.append(step)
    return {"answer": answer, "trace": trace, "truncated": truncated}


def _case(**kw):
    defaults = dict(id="c", member_id="M1001", task="t", expected_tools=["a", "b", "c"])
    defaults.update(kw)
    return EvalCase.from_dict(defaults)


def test_full_hit_passes():
    case = _case()
    result = _result(
        [["a"], ["b"], ["c", "log_visit_result"]],
        [_obs("a", {}), _obs("b", {}), _obs("c", {}) + _obs("log_visit_result", {})],
    )
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["tool_coverage"] == 1.0
    assert m["metrics"]["task_completion"] == 1.0
    assert m["passed"] is True
    assert m["total_score"] >= 0.7


def test_missing_tool_lowers_coverage():
    case = _case()
    result = _result([["a"]], [_obs("a", {})])
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["tool_coverage"] == round(1 / 3, 4)


def test_wrong_order_penalizes():
    case = _case(expected_order=["a", "b", "c"])
    result = _result(
        [["b"], ["a"], ["c"]],
        [_obs("b", {}), _obs("a", {}), _obs("c", {})],
    )
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["tool_coverage"] == round(1.0 - 0.1, 4)  # 全命中但顺序错 → 0.9


def test_order_bonus_capped():
    case = _case(expected_order=["a", "b", "c"])
    result = _result(
        [["a"], ["b"], ["c"]],
        [_obs("a", {}), _obs("b", {}), _obs("c", {})],
    )
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["tool_coverage"] == 1.0


def test_must_not_call_zeroes_coverage():
    case = _case(must_not_call=["x"])
    result = _result([["x"]], [_obs("x", {})])
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["tool_coverage"] == 0.0


def test_truncated_fails_completion():
    case = _case()
    result = _result([["a"]], [_obs("a", {})], answer="", truncated=True)
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["task_completion"] == 0.0
    assert m["passed"] is False


def test_error_observation_lowers_robustness():
    case = _case()
    # 领域错误（未找到会员）是正常业务结果，不计为健壮性失败
    result = _result(
        [["a"], ["b"]],
        [_obs("a", {"error": "未找到会员: M9999"}), _obs("b", {})],
    )
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["robustness"] == 1.0
    # 执行级崩溃（参数解析失败）计为健壮性失败
    result2 = _result(
        [["a"], ["b"]],
        [_obs("a", {"error": "参数解析失败: Expecting value"}), _obs("b", {})],
    )
    m2 = evaluate_case(result2, case, max_steps=6)
    assert m2["metrics"]["robustness"] == 0.5


def test_missing_observation_lowers_no_fabrication():
    case = _case()
    result = _result([["a"], ["b"]], [[], _obs("b", {})])  # a 有 action 无 observation
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["no_fabrication"] == 0.5


def test_citation_required():
    kb = "search_knowledge_base"
    case = _case(requires_knowledge=True, expected_tools=[kb, "log_visit_result"])
    # 未调知识库
    m1 = evaluate_case(_result([["log_visit_result"]], [_obs("log_visit_result", {})], answer="ok"), case)
    assert m1["metrics"]["policy_citation"] == 0.0
    # 调了但无出处标注
    m2 = evaluate_case(
        _result(
            [["log_visit_result"], [kb]],
            [_obs("log_visit_result", {}), _obs(kb, {"source": "x"})],
            answer="ok",
        ),
        case,
    )
    assert m2["metrics"]["policy_citation"] == 0.0
    # 调了且有出处标注
    m3 = evaluate_case(
        _result(
            [["log_visit_result"], [kb]],
            [_obs("log_visit_result", {}), _obs(kb, {"source": "x"})],
            answer="ok（依据：积分规则 · 到期处理）",
        ),
        case,
    )
    assert m3["metrics"]["policy_citation"] == 1.0


def test_non_knowledge_case_citation_na():
    case = _case(requires_knowledge=False)
    result = _result([["a"]], [_obs("a", {})])
    m = evaluate_case(result, case, max_steps=6)
    assert m["metrics"]["policy_citation"] == 1.0


def test_efficiency():
    case = _case()
    m1 = evaluate_case(_result([["a"]], [_obs("a", {})]), case, max_steps=6)
    assert m1["metrics"]["efficiency"] == 1.0
    m6 = evaluate_case(_result([["a"]] * 6, [None] * 6), case, max_steps=6)
    assert m6["metrics"]["efficiency"] == 0.0


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == 1.0
