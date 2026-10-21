"""M5：生成器 → Agent 评测集回流 —— 命令行入口。

把生成器的业务场景（case 文件 + prompt 文件，可选生成的对话 messages）
自动转换为 EvalCase，运行时注入对应会员到 Agent 环境，与现有 testset.yaml
合并后跑评测。

运行方式（cwd 为项目根目录 e:\\Coding_python\\MilkTea\\dialog-sft-forge）：
    # 仅用 case+prompt 转换并回流 10 条，跑 FakeLLM 基线（默认不产对话）
    python -m agent.eval.backflow.run_backflow --num 10 --mock

    # 抽样 max_rows 条跑真实评测，需 AGENT_API_KEY
    python -m agent.eval.backflow.run_backflow --num 10 --limit 5

    # CLI 也支持从已生成的对话中间文件读取（--dialogues jsonl，可选）

零改盘：注入走内存缓存，mock_data.json 字节不变（git status 应无改动）。
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------- 路径引导 ----------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.core.config import load_agent_config, resolve_path  # noqa: E402
from agent.core.llm_client import LLMClient  # noqa: E402
from agent.eval.case_schema import load_testset  # noqa: E402
from agent.eval.report import write_report  # noqa: E402
from agent.eval.runner import run_eval  # noqa: E402

# backflow 包内部
from .bridge import member_id_for_case  # noqa: E402
from .convert import to_eval_case  # noqa: E402
from .seed import inject_for_case  # noqa: E402

logger = logging.getLogger("BackflowCLI")

AGENT_DIR = os.path.join(PROJECT_ROOT, "agent")
DEFAULT_CONFIG = os.path.join(AGENT_DIR, "config", "agent_config.yaml")
DEFAULT_CASES_DIR = os.path.join(PROJECT_ROOT, "demo", "data", "case", "cases")
DEFAULT_PROMPTS_DIR = os.path.join(PROJECT_ROOT, "demo", "data", "case", "prompts")
DEFAULT_TESTSET = os.path.join(AGENT_DIR, "eval", "testset.yaml")


# ---------------- 轻量 case 解析（不引生成器内部依赖） ----------------
def _parse_case_txt(path: str) -> Dict[str, str]:
    """解析 "- 字段：值"（兼容中文/英文冒号）的案例文件。"""
    case: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("- "):
                continue
            rest = line[2:]
            for sep in ("：", ":"):
                if sep in rest:
                    k, v = rest.split(sep, 1)
                    k = k.strip()
                    if k and k not in case:
                        case[k] = v.strip()
                    break
    return case


def _load_dialogues(path: str) -> Dict[str, List[Dict[str, str]]]:
    """读取可选 pedialogues jsonl（member_id 别名 -> messages 列表）。"""
    out: Dict[str, List[Dict[str, str]]] = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out.setdefault(str(rec.get("id")), []).append(rec)
    return out


def build_backflow_cases(
    cases_dir: str,
    prompts_dir: str,
    num: int,
    start_index: int,
    dialogues_path: str = "",
) -> List[Dict[str, Any]]:
    """从 case/prompt 目录构建回流用例样本（未注入 member_id/未加 id）。"""
    case_files = sorted(f for f in os.listdir(cases_dir) if f.endswith(".txt"))
    prompt_files = sorted(f for f in os.listdir(prompts_dir) if f.endswith(".txt"))
    if not case_files:
        raise FileNotFoundError(f"案例目录为空: {cases_dir}")

    dialogues = _load_dialogues(dialogues_path)
    samples: List[Dict[str, Any]] = []
    idx = start_index
    for i, cf in enumerate(case_files):
        if num is not None and len(samples) >= num:
            break
        name = os.path.splitext(cf)[0]
        case_path = os.path.join(cases_dir, cf)
        prompt_path = os.path.join(prompts_dir, f"{name}.txt")
        case = _parse_case_txt(case_path)
        prompts_raw: str = ""
        if os.path.isfile(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompts_raw = f.read()
        messages = dialogues.get(name, [])
        samples.append(
            {
                "case": case,
                "prompt_text": prompts_raw,
                "messages": messages,
                "name": name,
            }
        )
        idx += 1
    return samples


def run_direct(config, data_path, samples, testset) -> Dict[str, Any]:
    """回流核心：注入会员 + 转换 EvalCase + 合并 + run_eval。返回 run_eval 结果。"""
    for si, sample in enumerate(samples):
        idx = si + 1  # BF 编号从 1 起
        member_id = member_id_for_case(idx)
        inject_for_case(data_path, idx, sample["case"])
        _name = sample["name"]
        case_raw = {
            "id": f"BF{idx:04d}_{_name if _name else idx}",
            "member_id": member_id,
            "case": sample["case"],
            "prompt_text": sample["prompt_text"],
            "messages": sample["messages"],
        }
        eval_case = to_eval_case(case_raw["id"], member_id, sample["case"], sample["prompt_text"], sample["messages"])
        testset.append(eval_case)

    return run_eval(config, testset)


def main() -> int:
    parser = argparse.ArgumentParser(description="M5 生成器→Agent 评测集回流")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    parser.add_argument("-t", "--testset", default=DEFAULT_TESTSET)
    parser.add_argument("--cases-dir", default=DEFAULT_CASES_DIR)
    parser.add_argument("--prompts-dir", default=DEFAULT_PROMPTS_DIR)
    parser.add_argument("--dialogues", default="", help="可选：已生成对话 jsonl（示例格式见 _load_dialogues）")
    parser.add_argument("-n", "--num", type=int, default=10, help="回流 case 数")
    parser.add_argument("--start-index", type=int, default=1, help="BF 编号起始")
    parser.add_argument("--limit", type=int, default=None, help="评测抽样上限")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--mock", action="store_true", help="FakeLLM 基线（无 API Key）")
    parser.add_argument("--use-llm-judge", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    config = load_agent_config(args.config)
    testset = load_testset(args.testset)
    data_path = resolve_path(config.get("data.mock_data_path", ""), PROJECT_ROOT)

    if not args.mock and not LLMClient.from_config(config).api_key:
        print("[!] 未检测到 API Key：请设置 AGENT_API_KEY，或加 --mock 跑 FakeLLM 基线。")
        return 1

    samples = build_backflow_cases(args.cases_dir, args.prompts_dir, args.num, args.start_index, args.dialogues)
    print(f"\n回流 {len(samples)} 个案例 → Agent 评测（含原 testset {len(testset) - len(samples)} 条）")

    data = run_direct(config, data_path, samples, testset)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S") if isinstance(data["cases"], list) and data["cases"] else ""
    out_dir = os.path.join(os.path.join(PROJECT_ROOT, "output", "eval"), f"backflow_{ts or 'now'}")
    os.makedirs(out_dir, exist_ok=True)
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