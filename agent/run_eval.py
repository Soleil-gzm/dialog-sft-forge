#!/usr/bin/env python3
"""奶茶店会员回访 Agent 离线评测 —— 命令行入口（M3：Agent Eval）。

运行方式：
    真实评测（需 AGENT_API_KEY）：
        python agent/run_eval.py
    FakeLLM 基线（无 API Key，CI 可用）：
        python agent/run_eval.py --mock
    抽样 / 启用 LLM 裁判：
        python agent/run_eval.py --limit 3 --seed 42 --use-llm-judge

输出：output/eval/{时间戳}/ 下的 report.md / report.json / cases.json / failures/
"""

import argparse
import os
import sys
from datetime import datetime

# ---- 路径引导：把项目根目录加入 sys.path，保证 `import agent.*` 可用 ----
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(AGENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.core.config import load_agent_config  # noqa: E402
from agent.core.llm_client import LLMClient  # noqa: E402
from agent.eval.case_schema import load_testset  # noqa: E402
from agent.eval.report import write_report  # noqa: E402
from agent.eval.runner import run_eval  # noqa: E402

DEFAULT_CONFIG = os.path.join(AGENT_DIR, "config", "agent_config.yaml")
DEFAULT_TESTSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval", "testset.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(description="奶茶店会员回访 Agent 离线评测（M3）")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="Agent 配置文件路径")
    parser.add_argument("-t", "--testset", default=DEFAULT_TESTSET, help="评测集 YAML 路径")
    parser.add_argument(
        "-o", "--output-dir",
        default=os.path.join(PROJECT_ROOT, "output", "eval"),
        help="评测输出根目录（会在其下新建时间戳子目录）",
    )
    parser.add_argument("--limit", type=int, default=None, help="最多评测的用例数（随机抽样）")
    parser.add_argument("--seed", type=int, default=0, help="抽样随机种子")
    parser.add_argument(
        "--mock", action="store_true", help="使用 FakeLLM 跑「全对」基线，无需 API Key"
    )
    parser.add_argument(
        "--use-llm-judge", action="store_true", help="启用 LLM 裁判（需 API Key）"
    )
    args = parser.parse_args()

    config = load_agent_config(args.config)
    testset = load_testset(args.testset)

    # API Key 检查：mock 模式豁免
    if not args.mock and not LLMClient.from_config(config).api_key:
        print("[!] 未检测到 API Key：请设置环境变量 AGENT_API_KEY，或使用 --mock 跑 FakeLLM 基线。")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.output_dir, ts)
    os.makedirs(out_dir, exist_ok=True)

    data = run_eval(
        config,
        testset,
        limit=args.limit,
        seed=args.seed,
        mock=args.mock,
        use_llm_judge=args.use_llm_judge,
    )
    md = write_report(data, out_dir)

    s = data["summary"]
    print(
        f"\n评测完成：{s['num_cases']} 条用例，通过 {s['num_passed']}（{s['pass_rate']:.1%}），"
        f"平均总分 {s['avg_total_score']}"
    )
    print(f"报告：{md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
