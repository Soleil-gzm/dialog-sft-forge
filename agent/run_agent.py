#!/usr/bin/env python3
"""奶茶店会员回访 Agent —— 命令行入口（M1：手搓 ReAct + 工具调用 / M2：RAG 长期记忆）。

运行方式：
    单轮任务：
        python agent/run_agent.py --member-id M1001 --task "完成一次积分到期提醒回访"
    多轮会话（记忆跨轮保留）：
        python agent/run_agent.py --member-id M1001 -i
    对比演示（关闭记忆）：
        python agent/run_agent.py --member-id M1001 -i --no-memory

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
from agent.rag.retriever import build_retriever  # noqa: E402
from agent.tools.business_tools import build_registry  # noqa: E402

DEFAULT_CONFIG = os.path.join(AGENT_DIR, "config", "agent_config.yaml")


def _print_trace(trace, max_len: int = 400) -> None:
    """打印推理轨迹：思考 → 行动 → 观察。

    检索类工具的返回值较长，超出 max_len 时截断展示，避免刷屏。
    """
    for step in trace:
        print(f"[Step {step['step']}] 思考: {step.get('thought') or '(调用工具中)'}")
        if step.get("actions"):
            print(f"         调用: {', '.join(step['actions'])}")
        for obs in step.get("observations", []):
            result = obs["result"]
            if len(result) > max_len:
                result = f"{result[:max_len]}...（已截断，共 {len(obs['result'])} 字符）"
            print(f"         观察({obs['tool']}): {result}")


def _run_task(agent: ReActAgent, member_id: str, task: str) -> None:
    """执行一次回访任务并打印轨迹与答复。"""
    query = f"会员编号 {member_id}。任务：{task}"
    print(f"\n=== 任务 ===\n{query}\n")

    result = agent.run(query)

    print("=== 推理轨迹 ===")
    _print_trace(result["trace"])
    print("\n=== 最终答复 ===")
    print(result["answer"] or "(未产出答复)")
    if result.get("truncated"):
        print("\n[!] 达到最大推理步数，任务被截断，可调高 react.max_steps 后重试。")


def _chat_loop(agent: ReActAgent, member_id: str) -> None:
    """多轮会话：同一 agent 实例复用记忆，实现跨轮上下文。"""
    print("\n=== 多轮会话模式 ===")
    print("每行输入一个回访任务；输入 exit 退出。")
    if agent.memory is None:
        print("[!] 记忆已关闭（--no-memory），每轮互不感知上下文。")

    while True:
        try:
            task = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if not task:
            continue
        if task.lower() in {"exit", "quit"}:
            print("已退出。")
            break
        _run_task(agent, member_id, task)


def main() -> int:
    parser = argparse.ArgumentParser(description="奶茶店会员回访 Agent（ReAct + 工具调用）")
    parser.add_argument("--member-id", default="M1001", help="会员编号，如 M1001")
    parser.add_argument("--task", default="完成一次会员回访", help="回访任务描述")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="多轮会话模式（记忆跨轮保留）"
    )
    parser.add_argument(
        "--no-memory", action="store_true", help="关闭会话记忆，用于对比演示"
    )
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="配置文件路径")
    args = parser.parse_args()

    config = load_agent_config(args.config)
    data_path = resolve_path(config.get("data.mock_data_path"), PROJECT_ROOT)
    log_path = resolve_path(config.get("data.visit_log_path"), PROJECT_ROOT)

    retriever = build_retriever(config)
    registry = build_registry(
        data_path,
        log_path=log_path,
        enabled=config.get("tools.enabled"),
        retriever=retriever,
    )
    llm = LLMClient.from_config(config)

    if not llm.api_key:
        key_env = config.get("llm.api_key_env", "AGENT_API_KEY")
        print(f"[!] 未检测到 API Key：请设置环境变量 {key_env}，或写入仓库根目录 .env 后重试。")
        print(f"    已注册工具（{len(registry.names())} 个）：{', '.join(registry.names())}")
        return 1

    memory = None if args.no_memory else ShortTermMemory(
        max_turns=config.get("memory.max_turns", 10)
    )
    agent = ReActAgent(
        llm_client=llm,
        tool_registry=registry,
        system_prompt=config.get("prompt.system", ""),
        max_steps=config.get("react.max_steps", 6),
        tools_enabled=config.get("tools.enabled"),
        memory=memory,
    )

    if args.interactive:
        _chat_loop(agent, args.member_id)
    else:
        _run_task(agent, args.member_id, args.task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
