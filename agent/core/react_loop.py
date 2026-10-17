"""ReAct 推理循环：思考 → 行动 → 观察，直到产出最终答复。

核心机制（不依赖 LangChain / LangGraph，全部手写）：
  1. 把系统 Prompt + 历史上下文 + 用户任务 送入 LLM
  2. LLM 返回 tool_calls 时，逐个执行并把结果作为 observation 回填
  3. 重复上述过程，直到 LLM 不再调用工具（视为可答复）或达到最大步数
  4. 全过程记录 trace，供演示与 Eval 使用
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ReActLoop")


class ReActAgent:
    """最小 ReAct Agent：LLM 决策调工具 → 执行 → 回填 → 继续。"""

    def __init__(
        self,
        llm_client,
        tool_registry,
        system_prompt: str,
        max_steps: int = 6,
        tools_enabled: Optional[List[str]] = None,
        memory=None,
    ):
        self.llm = llm_client
        self.registry = tool_registry
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.tools_enabled = tools_enabled
        self.memory = memory

    def run(self, user_query: str) -> Dict[str, Any]:
        """执行一次回访任务，返回 {answer, trace, messages}。"""
        messages: List[Dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        # 注意：不能用 `if self.memory`——ShortTermMemory 实现了 __len__，
        # 空记忆会被判定为 False，导致记忆永远写不进去。必须显式判断 None。
        if self.memory is not None:
            messages.extend(self.memory.as_list())
        messages.append({"role": "user", "content": user_query})

        tool_schemas = self.registry.schemas(self.tools_enabled)
        trace: List[Dict[str, Any]] = []

        for step in range(1, self.max_steps + 1):
            message = self.llm.chat(messages, tools=tool_schemas)
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            trace.append(
                {
                    "step": step,
                    "thought": content,
                    "actions": [tc.get("function", {}).get("name") for tc in tool_calls],
                }
            )

            # 无工具调用 → 视为最终答复，任务结束
            if not tool_calls:
                if self.memory is not None:
                    self.memory.add({"role": "user", "content": user_query})
                    self.memory.add({"role": "assistant", "content": content})
                return {"answer": content, "trace": trace, "messages": messages}

            # 有工具调用 → 执行并回填 observation
            for tc in tool_calls:
                func = tc.get("function", {}) or {}
                name = func.get("name", "")
                arguments = func.get("arguments", "{}")
                observation = self.registry.execute(name, arguments)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": observation,
                    }
                )
                trace[-1].setdefault("observations", []).append(
                    {"tool": name, "result": observation}
                )

        logger.warning(f"达到最大步数 {self.max_steps}，未产出最终答复")
        return {"answer": "", "trace": trace, "messages": messages, "truncated": True}
