#!/usr/bin/env python3
"""奶茶店会员回访 Agent —— 命令行入口（M1：手搓 ReAct + 工具调用）。

运行方式：
    python agent/run_agent.py --member-id M1001 --task "完成一次积分到期提醒回访"

前置条件：
    在环境变量（或 .env）中配置 AGENT_API_KEY；
    可选：AGENT_BASE_URL / AGENT_MODEL 覆盖配置文件中的端点与模型。
"""

import argparse
import os
import sys

# ---- 路径引导：把项目根目录加入 sys.path，保证 `import agent.*` 可用 ----
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(AGENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.core.config import load_agent_config, resolve_path  # noqa: E402
from agent.core.llm_client import LLMClient  # noqa: E402
from agent.core.memory import ShortTermMemory  # noqa: E402
from agent.core.react_loop import ReActAgent  # noqa: E402
from agent.tools.business_tools import build_registry  # noqa: E402

DEFAULT_CONFIG = os.path.join(AGENT_DIR, "config", "agent_config.yaml")


def _print_trace(trace) -> None:
    """打印推理轨迹：思考 → 行动 → 观察。"""
    for step in trace:
        print(f"[Step {step['step']}] 思考: {step.get('thought') or '(调用工具中)'}")
        if step.get("actions"):
            print(f"           调用: {', '.join(step['actions'])}")
        for obs in step.get("observations", []):
            print(f"           观察({obs['tool']}): {obs['result']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="奶茶店会员回访 Agent（ReAct + 工具调用）")
    parser.add_argument("--member-id", default="M1001", help="会员编号，如 M1001")
    parser.add_argument("--task", default="完成一次会员回访", help="回访任务描述")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="配置文件路径")
    args = parser.parse_args()

    config = load_agent_config(args.config)
    data_path = resolve_path(config.get("data.mock_data_path"), PROJECT_ROOT)
    log_path = resolve_path(config.get("data.visit_log_path"), PROJECT_ROOT)

    registry = build_registry(data_path, log_path=log_path, enabled=config.get("tools.enabled"))
    llm = LLMClient.from_config(config)

    if not llm.api_key:
        key_env = config.get("llm.api_key_env", "AGENT_API_KEY")
        print(f"[!] 未检测到 API Key：请设置环境变量 {key_env} 后重试。")
        print(f"    已注册工具（{len(registry.names())} 个）：{', '.join(registry.names())}")
        return 1

    agent = ReActAgent(
        llm_client=llm,
        tool_registry=registry,
        system_prompt=config.get("prompt.system", ""),
        max_steps=config.get("react.max_steps", 6),
        tools_enabled=config.get("tools.enabled"),
        memory=ShortTermMemory(max_turns=config.get("memory.max_turns", 10)),
    )

    query = f"会员编号 {args.member_id}。任务：{args.task}"
    print(f"\n=== 任务 ===\n{query}\n")

    result = agent.run(query)

    print("=== 推理轨迹 ===")
    _print_trace(result["trace"])
    print("\n=== 最终答复 ===")
    print(result["answer"] or "(未产出答复)")
    if result.get("truncated"):
        print("\n[!] 达到最大推理步数，任务被截断，可调高 react.max_steps 后重试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
