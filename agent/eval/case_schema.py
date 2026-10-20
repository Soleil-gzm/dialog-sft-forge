"""评测集数据模型与加载。

评测集以 YAML 手写维护（agent/eval/testset.yaml），每一条用例描述：
  - 一次回访任务（member_id + task 文本）
  - 期望行为：必调工具、顺序约束、禁调工具、是否需要知识库、验收点

设计约束：
  - 字段白名单校验：未知字段直接报错，避免手写评测集时拼错字段名
  - 必填字段校验：id / member_id / task / expected_tools 缺失即报错
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

logger = logging.getLogger("EvalCase")

# 合法字段集合（其余视为拼写错误）
_VALID_FIELDS = {
    "id",
    "member_id",
    "task",
    "expected_tools",
    "expected_order",
    "must_not_call",
    "requires_knowledge",
    "acceptance",
}


@dataclass
class EvalCase:
    """一条评测用例：任务输入 + 期望行为。"""

    id: str
    member_id: str
    task: str
    expected_tools: List[str]  # 必调工具（命中率即工具覆盖率分子）
    expected_order: List[str] = field(default_factory=list)  # 期望的相对顺序（可省略）
    must_not_call: List[str] = field(default_factory=list)  # 禁调工具，命中记 0 分
    requires_knowledge: bool = False  # 知识型用例：需调 search_knowledge_base 且答复带出处
    acceptance: List[str] = field(default_factory=list)  # 验收点（人工核对，暂不计分）

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "EvalCase":
        unknown = set(raw) - _VALID_FIELDS
        if unknown:
            raise ValueError(f"case 含未知字段: {sorted(unknown)}")
        required = {"id", "member_id", "task", "expected_tools"}
        missing = required - set(raw)
        if missing:
            raise ValueError(f"case 缺少必填字段: {sorted(missing)}")
        if not str(raw.get("id") or "").strip() or not str(raw.get("member_id") or "").strip():
            raise ValueError(f"case 的 id / member_id 不能为空: {raw}")
        expected_tools = raw.get("expected_tools")
        if not isinstance(expected_tools, list) or not expected_tools:
            raise ValueError(f"expected_tools 必须为非空列表: case {raw.get('id')}")
        return cls(
            id=str(raw["id"]),
            member_id=str(raw["member_id"]),
            task=str(raw["task"]),
            expected_tools=[str(t) for t in expected_tools],
            expected_order=[str(t) for t in (raw.get("expected_order") or [])],
            must_not_call=[str(t) for t in (raw.get("must_not_call") or [])],
            requires_knowledge=bool(raw.get("requires_knowledge", False)),
            acceptance=[str(a) for a in (raw.get("acceptance") or [])],
        )


def load_testset(path: str) -> List[EvalCase]:
    """加载 YAML 评测集，返回 EvalCase 列表；id 重复即报错。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cases_raw = data.get("cases")
    if not isinstance(cases_raw, list):
        raise ValueError(f"testset 缺少 cases 列表: {path}")
    seen = set()
    cases: List[EvalCase] = []
    for raw in cases_raw:
        case = EvalCase.from_dict(raw)
        if case.id in seen:
            raise ValueError(f"case id 重复: {case.id}")
        seen.add(case.id)
        cases.append(case)
    logger.info("加载评测集 %s：%d 条用例", path, len(cases))
    return cases
