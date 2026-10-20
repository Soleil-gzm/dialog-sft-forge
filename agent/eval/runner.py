"""评测运行器：逐用例驱动 ReActAgent 运行并打分。

构建流程与 agent/run_agent.py 保持一致（复用现有函数），
评测是外围模块，不改动 Agent 核心逻辑。
"""

import logging
import os
import random
import sys
from typing import Any, Callable, Dict, List, Optional

# agent/eval/runner.py -> 项目根目录（上 3 级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core.config import load_agent_config, resolve_path  # noqa: E402
from agent.core.llm_client import LLMClient  # noqa: E402
from agent.core.react_loop import ReActAgent  # noqa: E402
from agent.eval.case_schema import EvalCase, load_testset  # noqa: E402
from agent.eval.fake_llm import FakeLLM  # noqa: E402
from agent.eval.judge import Judge, LLMJudge, RuleBasedJudge  # noqa: E402
from agent.rag.retriever import build_retriever  # noqa: E402
from agent.tools.business_tools import build_registry  # noqa: E402

logger = logging.getLogger("EvalRunner")

# LLM 工厂：case -> llm 实例（共享真实客户端或逐 case 构造 FakeLLM）
LLMFactory = Callable[[EvalCase], Any]


def _default_llm_factory(config, mock: bool, real_llm) -> LLMFactory:
    """mock=True 时按用例构造「全对」FakeLLM；否则共享真实 LLMClient。"""
    if mock:
        def factory(case: EvalCase):
            return FakeLLM(
                FakeLLM.perfect_script(case.expected_tools, case.member_id, case.requires_knowledge)
            )
        return factory

    def factory(case: EvalCase):
        return real_llm
    return factory


def run_eval(
    config,
    testset: List[EvalCase],
    limit: Optional[int] = None,
    seed: int = 0,
    mock: bool = False,
    use_llm_judge: bool = False,
    llm_factory: Optional[LLMFactory] = None,
) -> Dict[str, Any]:
    """执行评测，返回 {cases, results, summary}。

    Args:
        config: 已加载的 AgentConfig
        testset: EvalCase 列表
        limit: 最多评测的用例数（从测试集随机抽样）
        seed: 抽样随机种子
        mock: 使用 FakeLLM（无 API Key 可跑，全对基线）
        use_llm_judge: 启用 LLM 裁判（需真实 LLM）
        llm_factory: 测试注入用，case -> llm 实例；优先于 mock
    """
    max_steps = int(config.get("react.max_steps", 6))
    data_path = resolve_path(config.get("data.mock_data_path", ""), PROJECT_ROOT)
    log_path = resolve_path(config.get("data.visit_log_path", ""), PROJECT_ROOT)

    retriever = build_retriever(config)
    registry = build_registry(
        data_path,
        log_path=log_path,
        enabled=config.get("tools.enabled"),
        retriever=retriever,
    )
    real_llm = LLMClient.from_config(config)

    if llm_factory is None:
        llm_factory = _default_llm_factory(config, mock, real_llm)

    judge: Judge = (
        LLMJudge(real_llm, max_steps=max_steps) if use_llm_judge
        else RuleBasedJudge(max_steps=max_steps)
    )

    # 抽样：limit 小于测试集规模时按 seed 随机抽样
    cases: List[EvalCase] = list(testset)
    if limit is not None and 0 < limit < len(cases):
        rng = random.Random(seed)
        cases = rng.sample(cases, limit)

    results: List[Dict[str, Any]] = []
    for case in cases:
        llm = llm_factory(case)
        agent = ReActAgent(
            llm_client=llm,
            tool_registry=registry,
            system_prompt=config.get("prompt.system", ""),
            max_steps=max_steps,
            tools_enabled=config.get("tools.enabled"),
            memory=None,  # 评测为单轮任务，不启用跨轮记忆
        )
        query = f"会员编号 {case.member_id}。任务：{case.task}"
        result = agent.run(query)
        score = judge.judge(result, case)

        record = {
            "case_id": case.id,
            "member_id": case.member_id,
            "task": case.task,
            "answer": result.get("answer", ""),
            "steps": score["steps"],
            "truncated": score["truncated"],
            "actions": score["actions"],
            "total_score": score["total_score"],
            "passed": score["passed"],
            "metrics": score["metrics"],
        }
        if not score["passed"]:
            record["trace"] = result.get("trace", [])  # 失败样本保留轨迹
        results.append(record)
        logger.info(
            "[%s] %s pass=%s score=%.3f steps=%d",
            case.id, case.member_id, record["passed"], record["total_score"], record["steps"],
        )

    summary = _summarize(results)
    return {"cases": cases, "results": results, "summary": summary, "use_llm_judge": use_llm_judge}


def _summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """聚合：各指标均值、总分均值、通过率。"""
    n = len(results) or 1
    total = sum(r["total_score"] for r in results) / n
    passed = sum(1 for r in results if r["passed"])
    metric_keys = [
        "tool_coverage", "task_completion", "robustness",
        "policy_citation", "no_fabrication", "efficiency",
    ]
    means = {
        k: round(sum(r["metrics"].get(k, 0.0) for r in results) / n, 4) for k in metric_keys
    }
    return {
        "num_cases": len(results),
        "num_passed": passed,
        "pass_rate": round(passed / n, 4),
        "avg_total_score": round(total, 4),
        "avg_metrics": means,
    }
