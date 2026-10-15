"""短期记忆：多轮上下文滑窗截断。

M1 只实现短期记忆（同一次任务内的上下文）。
M2 将在此基础上接入 RAG 长期记忆（跨会话）。
"""

from typing import Any, Dict, List


class ShortTermMemory:
    """保留最近 N 轮的对话消息，超出窗口的最早消息被丢弃。"""

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self._messages: List[Dict[str, Any]] = []

    def add(self, message: Dict[str, Any]) -> None:
        self._messages.append(message)
        self._truncate()

    def extend(self, messages: List[Dict[str, Any]]) -> None:
        self._messages.extend(messages)
        self._truncate()

    def _truncate(self) -> None:
        # 一轮 ≈ user + assistant 两条消息，按 2 倍消息数粗略限制窗口
        max_messages = self.max_turns * 2
        if len(self._messages) > max_messages:
            self._messages = self._messages[-max_messages:]

    def as_list(self) -> List[Dict[str, Any]]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
