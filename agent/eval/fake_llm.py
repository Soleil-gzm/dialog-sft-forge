"""FakeLLM：与 LLMClient.chat 契约一致的脚本化替身。

用途：
  - CI / 无 API Key 环境下跑评测管道
  - 单元测试中注入「全对 / 含错误行为」脚本，覆盖评分各分支

契约（与 agent/core/llm_client.py 的 chat 一致）：
    chat(messages, tools=None) -> message dict
其中 message dict 可含 tool_calls：
    [{"id": "...", "function": {"name": "...", "arguments": "..."}}]
"""

import json
from typing import Any, Dict, List, Optional


def tool_call(name: str, arguments: Optional[Dict[str, Any]] = None, idx: int = 1) -> Dict[str, Any]:
    """构造一条 OpenAI 风格的 tool_calls 项。"""
    return {
        "id": f"call_{idx}",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments or {}, ensure_ascii=False),
        },
    }


class FakeLLM:
    """按脚本依次返回消息；脚本用尽后返回无工具调用的兜底答复。

    脚本项格式（每项一步）：
        {"tool_calls": [tool_call(...), ...]}   调工具
        {"content": "最终答复"}                  无工具调用 → 任务结束
    """

    def __init__(self, script: Optional[List[Dict[str, Any]]] = None):
        self.script = list(script or [])
        self._idx = 0
        self.calls = 0

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        self.calls += 1
        if self._idx >= len(self.script):
            return {"role": "assistant", "content": "（脚本已用尽，任务结束）"}
        step = self.script[self._idx]
        self._idx += 1
        msg: Dict[str, Any] = {"role": "assistant", "content": step.get("content", "")}
        if step.get("tool_calls"):
            msg["tool_calls"] = step["tool_calls"]
        return msg

    @staticmethod
    def perfect_script(
        expected_tools: List[str],
        member_id: str = "M1001",
        requires_knowledge: bool = False,
    ) -> List[Dict[str, Any]]:
        """构造「全对」脚本：按序调用所有必调工具（参数匹配真实工具签名），再给出带出处标注的答复。"""
        script = [
            {"tool_calls": [tool_call(name, _tool_arguments(name, member_id), idx=i + 1)]}
            for i, name in enumerate(expected_tools)
        ]
        answer = "已完成回访。"
        if requires_knowledge:
            answer += "积分到期后将自动清零（依据：积分规则 · 到期处理）。"
        script.append({"content": answer})
        return script


def _tool_arguments(name: str, member_id: str) -> Dict[str, Any]:
    """按工具真实参数签名返回 mock 参数，保证 FakeLLM 全对脚本不触发工具报错。"""
    if name == "check_inventory":
        return {"product_name": "茉莉奶绿"}
    if name == "calc_best_coupon":
        return {"member_id": member_id}
    if name == "generate_followup_text":
        return {"member_id": member_id, "intent": "积分到期提醒"}
    if name == "log_visit_result":
        return {"member_id": member_id, "outcome": "已触达", "note": "评测用例"}
    if name == "search_knowledge_base":
        return {"query": "积分到期清零规则"}
    if name == "recall_member_history":
        return {"member_id": member_id}
    return {"member_id": member_id}
