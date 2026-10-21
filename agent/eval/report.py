"""评测报告生成：Markdown 摘要 + JSON 全量 + 失败样本。

输出结构（output/eval/{时间戳}/）：
    report.md      人读摘要与逐用例得分表
    report.json    全量结果（含聚合 summary）
    cases.json     评测集用例定义
    failures/      失败样本（case + answer + trace）
"""

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("EvalReport")

_METRIC_LABELS = {
    "tool_coverage": "工具覆盖",
    "task_completion": "任务完成",
    "robustness": "工具健壮",
    "policy_citation": "政策引用",
    "no_fabrication": "禁止编造",
    "efficiency": "效率",
}


def write_report(data: Dict[str, Any], output_dir: str) -> str:
    """把 run_eval 的返回结果写入 output_dir，返回 report.md 路径。"""
    os.makedirs(output_dir, exist_ok=True)
    results: List[Dict[str, Any]] = data["results"]
    summary: Dict[str, Any] = data["summary"]

    # 1. cases.json：用例定义
    with open(os.path.join(output_dir, "cases.json"), "w", encoding="utf-8") as f:
        json.dump([_case_to_dict(c) for c in data["cases"]], f, ensure_ascii=False, indent=2)

    # 2. report.json：全量结果
    with open(os.path.join(output_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)

    # 3. failures/：失败样本
    fail_dir = os.path.join(output_dir, "failures")
    os.makedirs(fail_dir, exist_ok=True)
    for r in results:
        if r["passed"]:
            continue
        with open(os.path.join(fail_dir, f"{r['case_id']}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)

    # 4. report.md
    md = _render_markdown(results, summary, data["use_llm_judge"])
    md_path = os.path.join(output_dir, "report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    logger.info("评测报告已写入 %s（%d 条用例，%s 条失败样本）",
                output_dir, summary["num_cases"], summary["num_cases"] - summary["num_passed"])
    return md_path


def _case_to_dict(case) -> Dict[str, Any]:
    return {
        "id": case.id,
        "member_id": case.member_id,
        "task": case.task,
        "expected_tools": case.expected_tools,
        "expected_order": case.expected_order,
        "must_not_call": case.must_not_call,
        "requires_knowledge": case.requires_knowledge,
        "acceptance": case.acceptance,
    }


def _render_markdown(results: List[Dict[str, Any]], summary: Dict[str, Any], use_llm_judge: bool) -> str:
    lines: List[str] = []
    lines.append("# Agent Eval 评测报告")
    lines.append("")
    lines.append(f"- 用例数：{summary['num_cases']}")
    lines.append(f"- 通过：{summary['num_passed']} / {summary['num_cases']}（通过率 {summary['pass_rate']:.1%}）")
    lines.append(f"- 平均总分：{summary['avg_total_score']}")
    lines.append(f"- 评分方式：{'规则 + LLM 裁判' if use_llm_judge else '规则判定'}")
    lines.append("")
    lines.append("## 指标均值")
    lines.append("")
    lines.append("| 指标 | 均值 |")
    lines.append("|---|---|")
    for key, label in _METRIC_LABELS.items():
        lines.append(f"| {label} | {summary['avg_metrics'].get(key, 0.0)} |")
    lines.append("")
    lines.append("## 逐用例得分")
    lines.append("")
    lines.append("| 用例 | 会员 | 通过 | 总分 | LLM质量分 | 工具覆盖 | 任务完成 | 健壮 | 政策引用 | 编造 | 效率 | 步数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        m = r["metrics"]
        q = m.get("quality_score")
        q_str = f"{q:.3f}" if q is not None else "-"
        lines.append(
            "| {id} | {mid} | {pass_} | {score} | {q} | {tc} | {com} | {rob} | {cit} | {fab} | {eff} | {steps} |".format(
                id=r["case_id"],
                mid=r["member_id"],
                pass_="✅" if r["passed"] else "❌",
                score=r["total_score"],
                q=q_str,
                tc=m["tool_coverage"],
                com=m["task_completion"],
                rob=m["robustness"],
                cit=m["policy_citation"],
                fab=m["no_fabrication"],
                eff=m["efficiency"],
                steps=r["steps"],
            )
        )
    lines.append("")
    failed = [r for r in results if not r["passed"]]
    if failed:
        lines.append("## 失败样本")
        lines.append("")
        for r in failed:
            lines.append(f"- **{r['case_id']}**（{r['member_id']}）：总分 {r['total_score']}，步数 {r['steps']}"
                         f"{'，被截断' if r['truncated'] else ''}。详情见 `failures/{r['case_id']}.json`")
        lines.append("")
    lines.append("---")
    lines.append("*生成时间戳目录见上级目录名；规则判定为可复现的确定性指标。*")
    return "\n".join(lines)
