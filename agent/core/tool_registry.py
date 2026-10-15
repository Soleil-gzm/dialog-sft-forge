"""工具注册表：统一管理工具的 JSON Schema 与执行入口。

设计目标：
  - 工具以 JSON Schema 声明参数，直接转换为 OpenAI /chat/completions 的 tools 字段
  - 执行入口统一做参数解析与异常兜底，保证推理循环不因单个工具失败而中断
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("AgentToolRegistry")


@dataclass
class Tool:
    """一个可被 Agent 调用的工具。"""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    func: Callable[..., Any]

    def to_openai_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI /chat/completions 的 tools 字段格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册表：注册、查询、按 Schema 导出、执行。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具，重名时直接报错（避免静默覆盖）。"""
        if tool.name in self._tools:
            raise ValueError(f"工具已注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未注册的工具: {name}")
        return self._tools[name]

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def schemas(self, only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """导出工具的 OpenAI Schema 列表；only 可限定启用子集。"""
        names = only if only else self.names()
        return [self._tools[n].to_openai_schema() for n in names if n in self._tools]

    def execute(self, name: str, arguments: str) -> str:
        """执行工具。arguments 为 JSON 字符串，返回字符串结果供回填 observation。"""
        try:
            tool = self.get(name)
        except KeyError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"参数解析失败: {e}"}, ensure_ascii=False)

        try:
            result = tool.func(**args)
        except Exception as e:  # 工具内部异常不应中断推理循环
            logger.warning(f"工具 {name} 执行失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
