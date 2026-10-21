"""M5 闭环演示的薄适配层：把生成器产出的一条对话，跑成「回流 → Agent → 评测」四段展示。

不修改 Agent / 生成器核心，只做三件事：
  1. 把 Tab1 生成的 dialogue（case_info + messages）还原成完整 case + prompt
  2. 调用 backflow 的 convert / seed 得到 EvalCase 并注入运行时会员
  3. 调用 runner.run_single_case 执行并渲染成 HTML 片段

渲染函数返回 HTML 字符串，供 Gradio gr.HTML 直接展示。
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from agent.core.config import load_agent_config  # noqa: E402
from agent.eval.backflow.convert import to_eval_case  # noqa: E402
from agent.eval.backflow.run_backflow import parse_case_txt  # noqa: E402
from agent.eval.backflow.seed import inject_for_case  # noqa: E402
from agent.eval.runner import build_runtime, run_single_case  # noqa: E402

logger = logging.getLogger("LoopDemo")

AGENT_CONFIG = os.path.join(PROJECT_ROOT, "agent", "config", "agent_config.yaml")
CASES_DIR = os.path.join(PROJECT_ROOT, "demo", "data", "case", "cases")
PROMPTS_DIR = os.path.join(PROJECT_ROOT, "demo", "data", "case", "prompts")

_METRIC_LABELS = {
    "tool_coverage": "工具覆盖",
    "task_completion": "任务完成",
    "robustness": "工具健壮",
    "policy_citation": "政策引用",
    "no_fabrication": "禁止编造",
    "efficiency": "效率",
}

_RUNTIME_CACHE: Dict[str, Any] = {}


# ============================================================
# 运行时与配置
# ============================================================
def _load_config():
    if "config" not in _RUNTIME_CACHE:
        _RUNTIME_CACHE["config"] = load_agent_config(AGENT_CONFIG)
    return _RUNTIME_CACHE["config"]


def _runtime():
    if "runtime" not in _RUNTIME_CACHE:
        _RUNTIME_CACHE["runtime"] = build_runtime(_load_config())
    return _RUNTIME_CACHE["runtime"]


def has_api_key() -> bool:
    """真实模型是否可用（配置的 api_key 是否为空）。"""
    try:
        from agent.core.llm_client import LLMClient

        return bool(LLMClient.from_config(_load_config()).api_key)
    except Exception:  # 配置异常时按不可用处理
        return False


# ============================================================
# 输入还原
# ============================================================
def _case_number(case_file: str, dialogue_id: Optional[int]) -> int:
    """从 case_0007 提取 7；失败时退回 dialogue_id。"""
    m = re.search(r"(\d+)", str(case_file or ""))
    if m:
        return max(1, int(m.group(1)))
    return max(1, int(dialogue_id or 1))


def load_full_case(case_file: str, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """回读 case txt 拿全量字段（case_info 缺优惠券/性别等）；文件缺失则降级。"""
    path = os.path.join(CASES_DIR, f"{case_file}.txt")
    if case_file and os.path.isfile(path):
        return parse_case_txt(path)
    return {k: str(v) for k, v in (fallback or {}).items()}


def load_prompt(case_file: str) -> str:
    path = os.path.join(PROMPTS_DIR, f"{case_file}.txt")
    if case_file and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def prepare(dialogue: Dict[str, Any]) -> Dict[str, Any]:
    """把一条生成对话还原成闭环所需输入：case / prompt / messages / member_id。"""
    case_file = str(dialogue.get("case_file") or "")
    case = load_full_case(case_file, dialogue.get("case_info"))
    messages = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in (dialogue.get("messages") or [])
    ]
    index = _case_number(case_file, dialogue.get("dialogue_id"))
    member_id = f"BF{index:04d}"
    return {
        "case_file": case_file,
        "case": case,
        "prompt_text": load_prompt(case_file),
        "messages": messages,
        "index": index,
        "member_id": member_id,
        "dialogue_id": dialogue.get("dialogue_id"),
    }


# ============================================================
# 执行闭环
# ============================================================
def run_closed_loop(
    dialogue: Dict[str, Any],
    mode: str = "基线",
    use_llm_judge: bool = False,
    on_stage=None,
) -> Dict[str, Any]:
    """执行一次完整闭环，返回展示所需的所有数据。

    Args:
        dialogue: Tab1 中的一条对话（含 case_file / case_info / messages）
        mode: "基线"（FakeLLM，免 Key）或 "真实"
        use_llm_judge: 是否叠加 LLM 裁判质量分（仅真实模式有意义）
    """
    def stage(msg: str, frac: float):
        if on_stage:
            on_stage(msg, frac)

    stage("还原案例字段…", 0.1)
    ctx = prepare(dialogue)

    stage("回流转换为 EvalCase…", 0.3)
    eval_case = to_eval_case(
        case_id=f"{ctx['member_id']}_{ctx['case_file'] or ctx['dialogue_id']}",
        member_id=ctx["member_id"],
        case=ctx["case"],
        prompt_text=ctx["prompt_text"],
        messages=ctx["messages"],
    )

    stage("注入运行时会员…", 0.45)
    rt = _runtime()
    inject_for_case(rt["data_path"], ctx["index"], ctx["case"])
    member_profile = _query_profile(ctx["member_id"])

    stage("Agent 执行中…", 0.6)
    record = run_single_case(
        _load_config(),
        eval_case,
        mock=(mode != "真实"),
        use_llm_judge=bool(use_llm_judge and mode == "真实"),
        runtime=rt,
    )

    stage("评分完成", 1.0)
    return {
        "context": ctx,
        "eval_case": eval_case,
        "member_profile": member_profile,
        "record": record,
        "mode": mode,
    }


def _query_profile(member_id: str) -> Dict[str, Any]:
    """通过已注册工具读取注入后的会员画像（证明注入生效）。"""
    try:
        raw = _runtime()["registry"].execute("query_member_profile", json.dumps({"member_id": member_id}))
        return json.loads(raw)
    except Exception:  # 展示用途，失败不阻断
        return {}


# ============================================================
# 渲染
# ============================================================
def render_input_header(dialogue: Dict[str, Any]) -> str:
    if not dialogue:
        return '<div class="loop-hint">请先在「数据生成」页生成对话并选择一条，再回到此处运行闭环。</div>'
    info = dialogue.get("case_info") or {}
    bits = [f"对话 {dialogue.get('dialogue_id', '-')}", str(dialogue.get("case_file") or "-")]
    if info.get("会员等级"):
        bits.append(f"{info['会员等级']}会员")
    if info.get("客户姓名"):
        bits.append(str(info["客户姓名"]))
    text = " · ".join(html.escape(str(b)) for b in bits)
    return f'<div class="loop-input">当前输入：<b>{text}</b></div>'


def render_case_html(case: Dict[str, Any], case_file: str = "") -> str:
    fields = ["门店名称", "客户姓名", "客户性别", "会员等级", "积分余额",
              "优惠券", "到期日期", "消费金额"]
    items = "".join(
        f'<div class="dfs-card-item"><b>{html.escape(k)}</b>：{html.escape(str(case.get(k) or "—"))}</div>'
        for k in fields
    )
    head = f"原始案例（生成器）{(' · ' + case_file) if case_file else ''}"
    return (
        '<div class="dfs-card">'
        f'<div class="dfs-card-title">🧾 {html.escape(head)}</div>'
        f'<div class="dfs-card-grid">{items}</div>'
        "</div>"
    )


def render_evalcase_html(result: Dict[str, Any]) -> str:
    ctx = result["context"]
    ec = result["eval_case"]
    profile = result.get("member_profile") or {}
    tools = "".join(f'<span class="loop-chip">{html.escape(t)}</span>' for t in ec.expected_tools)
    kn = '<span class="loop-chip loop-chip-kn">需知识库</span>' if ec.requires_knowledge else ""
    acc = "".join(f"<li>{html.escape(a)}</li>" for a in ec.acceptance) or "<li>—</li>"
    member_line = " · ".join(
        html.escape(str(v)) for v in [
            ctx["member_id"], profile.get("name", "—"),
            profile.get("level", "—"), f"{profile.get('points', '—')}分",
        ]
    )
    return f"""
<div class="loop-panel">
  <div class="loop-panel-title">🔁 回流得到 EvalCase</div>
  <div class="loop-kv"><b>注入会员</b><span class="loop-member">{member_line}</span></div>
  <div class="loop-kv"><b>任务 task</b><div class="loop-task">{html.escape(ec.task)}</div></div>
  <div class="loop-kv"><b>期望工具</b><div>{tools}{kn}</div></div>
  <div class="loop-kv"><b>验收点</b><ul class="loop-acc">{acc}</ul></div>
</div>"""


def _fmt_obs(raw: str) -> str:
    try:
        obj = json.loads(raw)
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(raw)
    if len(text) > 900:
        text = text[:900] + "\n…（已截断）"
    return html.escape(text)


def render_trace_html(record: Dict[str, Any]) -> str:
    trace: List[Dict[str, Any]] = record.get("trace") or []
    parts = ['<div class="loop-panel"><div class="loop-panel-title">🤖 ReAct 执行轨迹</div>']
    if not trace:
        parts.append('<div class="loop-empty">无轨迹记录</div>')
    for step in trace:
        no = step.get("step", "?")
        thought = html.escape(str(step.get("thought") or "（无思考文本）"))
        actions = step.get("actions") or []
        action_html = "".join(
            f'<div class="loop-action">→ <code>{html.escape(str(a))}</code></div>' for a in actions
        )
        obs_html = ""
        for obs in step.get("observations") or []:
            obs_html += (
                '<details class="loop-obs">'
                f'<summary>observation · {html.escape(str(obs.get("tool", "")))}</summary>'
                f'<pre>{_fmt_obs(obs.get("result", ""))}</pre>'
                "</details>"
            )
        parts.append(
            '<div class="loop-step">'
            f'<div class="loop-step-head"><span class="loop-step-no">{no}</span>思考</div>'
            f'<div class="loop-thought">{thought}</div>'
            f"{action_html}{obs_html}"
            "</div>"
        )
    answer = html.escape(str(record.get("answer") or "（无最终答复）"))
    parts.append(
        '<div class="loop-answer"><div class="loop-answer-title">最终答复</div>'
        f'<div class="loop-answer-body">{answer}</div></div>'
    )
    parts.append("</div>")
    return "".join(parts)


def render_metrics_html(record: Dict[str, Any], mode: str = "") -> str:
    m = record.get("metrics") or {}
    passed = record.get("passed")
    badge = (
        '<span class="loop-badge ok">✅ 通过</span>' if passed
        else '<span class="loop-badge bad">❌ 未通过</span>'
    )
    cards = "".join(
        f'<div class="loop-metric"><span>{label}</span><b>{m.get(key, 0):.2f}</b></div>'
        for key, label in _METRIC_LABELS.items()
    )
    q = m.get("quality_score")
    if q is not None:
        cards += f'<div class="loop-metric"><span>LLM质量分</span><b>{q:.2f}</b></div>'
    meta = f"评分方式：{html.escape(mode or '规则判定')} · 步数 {record.get('steps', '-')}"
    trunc = '<span class="loop-badge warn">⚠ 达到最大步数</span>' if record.get("truncated") else ""
    return f"""
<div class="loop-panel">
  <div class="loop-score-head">
    <div class="loop-score">总分 <b>{record.get('total_score', 0):.3f}</b></div>
    {badge}{trunc}
  </div>
  <div class="loop-metrics">{cards}</div>
  <div class="loop-meta">{meta}</div>
</div>"""


def render_error_html(msg: str) -> str:
    return f'<div class="loop-panel loop-error">执行失败：{html.escape(str(msg))}</div>'
