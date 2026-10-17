"""Agent 核心骨架测试（不依赖 LLM）：工具注册表 / 业务工具 / 短期记忆。

运行：pytest agent/tests -v
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.core.memory import ShortTermMemory  # noqa: E402
from agent.core.react_loop import ReActAgent  # noqa: E402
from agent.core.tool_registry import Tool, ToolRegistry  # noqa: E402
from agent.tools.business_tools import build_registry  # noqa: E402

MOCK_DATA = os.path.join(PROJECT_ROOT, "agent", "data", "mock_data.json")

ALL_TOOL_NAMES = [
    "query_member_profile",
    "query_purchase_history",
    "check_inventory",
    "calc_best_coupon",
    "generate_followup_text",
    "log_visit_result",
]


@pytest.fixture()
def registry(tmp_path):
    """构建一个使用临时日志路径的工具注册表。"""
    return build_registry(MOCK_DATA, log_path=str(tmp_path / "visit_log.jsonl"))


# ---------------- 工具注册表 ----------------

def test_registry_registers_all_tools(registry):
    assert sorted(registry.names()) == sorted(ALL_TOOL_NAMES)


def test_tool_openai_schema_format(registry):
    schema = registry.schemas(["query_member_profile"])[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "query_member_profile"
    assert "member_id" in schema["function"]["parameters"]["properties"]


def test_registry_rejects_duplicate_tool():
    reg = ToolRegistry()
    tool = Tool(name="t", description="d", parameters={"type": "object"}, func=lambda: 1)
    reg.register(tool)
    with pytest.raises(ValueError):
        reg.register(tool)


def test_registry_execute_bad_json_returns_error(registry):
    result = json.loads(registry.execute("query_member_profile", "{not json"))
    assert "error" in result


def test_registry_execute_unknown_tool_returns_error(registry):
    result = json.loads(registry.execute("no_such_tool", "{}"))
    assert "error" in result


def test_registry_enabled_filter(tmp_path):
    reg = build_registry(MOCK_DATA, log_path=str(tmp_path / "log.jsonl"), enabled=["check_inventory"])
    assert reg.names() == ["check_inventory"]


# ---------------- 业务工具 ----------------

def test_query_member_profile(registry):
    result = json.loads(registry.execute("query_member_profile", '{"member_id": "M1001"}'))
    assert result["name"] == "李雪"
    assert result["level"] == "VIP"


def test_query_member_profile_not_found(registry):
    result = json.loads(registry.execute("query_member_profile", '{"member_id": "NOPE"}'))
    assert "error" in result


def test_query_purchase_history_limit(registry):
    result = json.loads(
        registry.execute("query_purchase_history", '{"member_id": "M1001", "limit": 1}')
    )
    assert len(result["records"]) == 1


def test_check_inventory(registry):
    result = json.loads(registry.execute("check_inventory", '{"product_name": "桂花乌龙"}'))
    assert result["status"] == "缺货"


def test_calc_best_coupon_picks_max_discount(registry):
    result = json.loads(registry.execute("calc_best_coupon", '{"member_id": "M1001"}'))
    assert result["coupon"]["discount"] == 15


def test_generate_followup_text_fills_placeholders(registry):
    result = json.loads(
        registry.execute("generate_followup_text", '{"member_id": "M1001", "intent": "积分到期提醒"}')
    )
    assert "李雪" in result["text"]
    assert "1250" in result["text"]
    assert "{" not in result["text"]  # 占位符应全部被替换


def test_log_visit_result_writes_file(registry, tmp_path):
    result = json.loads(
        registry.execute("log_visit_result", '{"member_id": "M1001", "outcome": "已触达"}')
    )
    assert result["ok"] is True
    assert os.path.exists(result["file"])


# ---------------- 短期记忆 ----------------

def test_memory_sliding_window():
    memory = ShortTermMemory(max_turns=2)
    for i in range(5):
        memory.add({"role": "user", "content": f"u{i}"})
        memory.add({"role": "assistant", "content": f"a{i}"})
    messages = memory.as_list()
    assert len(messages) == 4  # max_turns * 2
    assert messages[0]["content"] == "u3"  # 最早的已被丢弃


def test_memory_clear():
    memory = ShortTermMemory(max_turns=3)
    memory.add({"role": "user", "content": "hi"})
    memory.clear()
    assert len(memory) == 0


# ---------------- 多轮会话记忆 ----------------


class _FakeLLM:
    """不调用工具的假 LLM：直接返回文本，便于验证跨轮上下文。"""

    def __init__(self):
        self.requests = []

    def chat(self, messages, tools=None):
        self.requests.append([m.get("content") for m in messages])
        return {"role": "assistant", "content": f"第 {len(self.requests)} 轮答复"}


def test_multi_turn_reuses_memory():
    llm = _FakeLLM()
    memory = ShortTermMemory(max_turns=10)
    agent = ReActAgent(llm, ToolRegistry(), "系统提示", memory=memory)

    agent.run("第一轮问题")
    agent.run("第二轮问题")

    # 两轮 × (user + assistant)
    assert len(memory) == 4
    assert memory.as_list()[0]["content"] == "第一轮问题"

    # 第二轮请求中应携带第一轮问答
    second_request = llm.requests[1]
    assert "第一轮问题" in second_request
    assert "第 1 轮答复" in second_request


def test_multi_turn_without_memory_is_isolated():
    llm = _FakeLLM()
    agent = ReActAgent(llm, ToolRegistry(), "系统提示", memory=None)

    agent.run("第一轮问题")
    agent.run("第二轮问题")

    # 关闭记忆后，第二轮请求不应包含第一轮内容
    assert "第一轮问题" not in llm.requests[1]
