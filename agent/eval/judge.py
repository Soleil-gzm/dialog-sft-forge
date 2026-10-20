"""评测裁判抽象：默认规则判定，预留 LLM 裁判接口（默认关闭）。

  RuleBasedJudge  确定性规则打分（metrics.evaluate_case）
  LLMJudge        预留：在规则分基础上，用 LLM 对答复质量额外打分（--use-llm-judge）

设计目标：切换裁判只需替换注入对象，不影响 runner 与报告逻辑。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

from agent.eval.case_schema import EvalCase
from agent.eval.metrics import evaluate_case

logger = logging.getLogger("EvalJudge")


class Judge(ABC):
    """裁判基类：judge(result, case) -> 带总分的指标 dict。"""

    def __init__(self, max_steps: int = 6):
        self.max_steps = max_steps

    @abstractmethod
    def judge(self, result: Dict[str, Any], case: EvalCase) -> Dict[str, Any]:
        ...


class RuleBasedJudge(Judge):
    """规则判定：确定性、零额外 LLM 成本。"""

    def judge(self, result: Dict[str, Any], case: EvalCase) -> Dict[str, Any]:
        return evaluate_case(result, case, max_steps=self.max_steps)


class LLMJudge(Judge):
    """LLM 裁判（预留）：在规则分基础上追加答复质量分。

    启用方式：run_eval.py --use-llm-judge，并向构造注入已就绪的 LLMClient。
    打分：把 case 期望与最终答复组装成提示词，让 LLM 返回 0~1 质量分。
    """

    def __init__(self, llm_client, max_steps: int = 6):
        super().__init__(max_steps=max_steps)
        self.llm = llm_client
        self._rule = RuleBasedJudge(max_steps=max_steps)

    def judge(self, result: Dict[str, Any], case: EvalCase) -> Dict[str, Any]:
        base = self._rule.judge(result, case)
        try:
            quality = self._score_quality(case, result.get("answer", ""))
        except Exception as e:  # LLM 失败不阻断评测
            logger.warning("LLM 裁判打分失败，质量分按 0.5 计：%s", e)
            quality = 0.5
        base["metrics"]["quality_score"] = round(quality, 4)
        base["llm_judged"] = True
        return base

    def _score_quality(self, case: EvalCase, answer: str) -> float:
        prompt = (
            "你是评测裁判。判断下面的会员回访答复是否符合任务要求，"
            "只输出一个 0 到 1 之间的小数表示质量分。\n"
            f"任务：{case.task}\n"
            f"验收点：{case.acceptance or '无'}\n"
            f"答复：{answer[:800]}"
        )
        message = self.llm.chat(
            [{"role": "system", "content": "你是评测裁判。"}, {"role": "user", "content": prompt}]
        )
        text = (message.get("content") or "").strip()
        try:
            return float(text)
        except ValueError:
            logger.warning("LLM 裁判输出无法解析为分数: %r", text)
            return 0.5
