#!/usr/bin/env python3
"""
奶茶店会员回访 Demo — Gradio 展示型界面

基于多轮对话合成系统（dialog-sft-forge），使用完全虚构的奶茶店会员回访场景，
展示从话术模板 + 概率矩阵 → 路径生成 → 多轮对话合成的完整流程。

运行方式：
  python demo/app.py
"""

import json
import logging
import os
import sys

import pandas as pd
import yaml

# ============================================================
# 路径设置（必须在 core 导入之前）
#
# 无论从哪个工作目录运行 `python demo/app.py`，都把以下路径加入 sys.path：
#   - PROJECT_ROOT → 支持 import scripts_general / demo（HF Spaces 转发入口）
#   - SCRIPTS_DIR  → 支持 core 内部统一的 `from core.xxx` 导入风格
#   - DEMO_DIR     → 支持 import generate_demo_data
# ============================================================
DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DEMO_DIR)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts_general")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, DEMO_DIR)  # 为了 import generate_demo_data

# ============================================================
# 自动生成 demo 数据（如果缺失）
# ============================================================
DATA_DIR = os.path.join(DEMO_DIR, "data")
CONFIG_PATH = os.path.join(DEMO_DIR, "config", "demo_config.yaml")

REPO_URL = "https://github.com/Soleil-gzm/dialog-sft-forge"
SPACE_URL = "https://huggingface.co/spaces/Soleil-gzm/dialog-sft-forge"


def ensure_demo_data():
    """检查 demo/data 是否存在，缺失则自动生成"""
    prob_path = os.path.join(DATA_DIR, "prob.xlsx")
    if not os.path.exists(prob_path):
        print("demo 数据缺失，自动生成中...")
        from generate_demo_data import main as _gen

        _gen()
        print("demo 数据生成完成。\n")


ensure_demo_data()

# ============================================================
# core 模块导入
# ============================================================
import gradio as gr

from core.data.data_loader import load_prob_matrix, load_sheets
from core.generation.config import load_config, sync_config_from_prob
from core.generation.dialogue_builder import DialogueBuilder
from core.generation.factory import create_case_loader, create_time_generator
from core.pressure.pressure_manager import PressureManager
from core.utils.path_generator import PathGenerator
from core.utils.random_service import RandomService

import loop_demo  # 闭环评测（回流 → Agent → 评测）展示适配层

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("DemoApp")


# ============================================================
# 视觉资源：主题 / CSS / Banner
# ============================================================

def create_theme():
    """奶茶色系主题：主色为与 CSS 调色板一致的哑光深绿（#2E7D5B）

    Gradio 内置的 "green" 色阶是高饱和的亮绿，会和自定义 CSS 里的暗绿
    （Banner / 卡片 / 热力图）风格不统一。这里用自定义 Color 覆盖整条色阶，
    让按钮、滑块、Radio 选中态、标签底色都落到同一套低饱和绿上。
    """
    milk_green = gr.themes.Color(
        name="milk_green",
        c50="#F2F8F5",
        c100="#DFEEE7",
        c200="#C1DDCE",
        c300="#97C4AC",
        c400="#6AA886",
        c500="#2E7D5B",  # 主色（与 Banner / 卡片 / 热力图一致）
        c600="#26684C",
        c700="#1F5340",
        c800="#194234",
        c900="#123027",
        c950="#0A1F19",
    )
    return gr.themes.Soft(
        primary_hue=milk_green,
        secondary_hue="orange",
        neutral_hue="stone",
        font=[gr.themes.GoogleFont("Noto Sans SC"), "ui-sans-serif", "system-ui"],
    ).set(
        # 默认 hover 会跳到更亮的 primary_400，为避免"悬停变亮绿"，改为变深
        button_primary_background_fill_hover="*primary_600",
    )


CSS = """
/* ---- 顶部 Banner ---- */
.dfs-banner {
  background: linear-gradient(135deg, #1F6B4E 0%, #2E7D5B 45%, #62B88F 100%);
  border-radius: 18px;
  padding: 26px 30px;
  margin-bottom: 14px;
  box-shadow: 0 10px 28px rgba(31, 107, 78, 0.28);
}
.dfs-banner-title {
  color: #FFFFFF;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}
.dfs-banner-sub {
  color: #DCF3E7;
  font-size: 15px;
  margin-bottom: 16px;
}
.dfs-banner-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.dfs-tag {
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.35);
  color: #FFFFFF;
  border-radius: 999px;
  padding: 4px 14px;
  font-size: 13px;
}

/* ---- 导航条 ---- */
.dfs-nav a {
  display: inline-block;
  margin-right: 10px;
  padding: 5px 14px;
  border-radius: 999px;
  background: #F1F5F3;
  color: #1F6B4E !important;
  font-size: 13px;
  text-decoration: none;
  border: 1px solid #DCE9E2;
}
.dfs-nav a:hover { background: #E1EFE8; }

/* ---- 概率矩阵热力图 ---- */
.dfs-heat { overflow-x: auto; max-height: 460px; border-radius: 12px; }
.dfs-heat-table {
  border-collapse: collapse;
  font-size: 12px;
  width: 100%;
}
.dfs-heat-table th, .dfs-heat-table td {
  padding: 5px 8px;
  text-align: center;
  white-space: nowrap;
  border: 1px solid #EAF1ED;
}
.dfs-heat-table thead th, .dfs-heat-table .rowh {
  background: #F4F8F6;
  color: #33473E;
  font-weight: 600;
  position: sticky;
  top: 0;
}
.dfs-heat-table .rowh { position: sticky; left: 0; top: auto; }

/* ---- 案例信息卡 ---- */
.dfs-card {
  background: #F7FBF9;
  border: 1px solid #DCE9E2;
  border-left: 5px solid #2E7D5B;
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 10px;
}
.dfs-card-title {
  color: #1F6B4E;
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 10px;
}
.dfs-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px 16px;
}
.dfs-card-item { font-size: 13px; color: #33473E; }
.dfs-card-item b { color: #1F6B4E; font-weight: 600; }

/* ---- 对话气泡 ---- */
.dfs-chat-hint {
  font-size: 13px;
  color: #64748B;
  margin-bottom: 6px;
}

/* ---- 统计条 ---- */
.dfs-stats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.dfs-stat {
  background: #F1F5F3;
  border-radius: 10px;
  padding: 8px 16px;
  font-size: 13px;
  color: #33473E;
}
.dfs-stat b { color: #1F6B4E; font-size: 16px; }

footer { visibility: hidden; }

/* ---- 结果区：两列固定高度，底部对齐 ---- */
#result-left-col, #result-right-col {
  height: 640px !important;
}

/* ---- 结果区左列：路径(4) / 选择器(6) 按比例分配，按钮与统计自然高度 ---- */
#result-left-col {
  display: flex;
  flex-direction: column;
}
/* 路径展示（gr.Code） */
#paths_display {
  flex: 4;
  min-height: 0;
  height: auto !important;
  display: flex;
  flex-direction: column;
}
#paths_display > div.wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
#paths_display .codemirror-wrapper,
#paths_display .cm-editor {
  flex: 1;
  min-height: 0;
}
#paths_display .cm-scroller {
  flex: 1 !important;
  min-height: 0 !important;
  max-height: none !important;
  height: 100% !important;
  overflow-y: auto !important;
}
/* 对话选择器（被 div.form 包裹） */
#result-left-col > .form {
  flex: 6 !important;
  min-height: 0 !important;
  overflow-y: auto;
}
/* 下载按钮与统计块取内容高度，不参与 flex 拉伸，由 paths/selector 填满空间 */
#result-left-col > button,
#result-left-col > .block.hide-container {
  flex: 0 0 auto !important;
  --block-padding: 0 12px;
}

/* ---- 结果区右列：chatbot 紧贴 case_card 下方，底部对齐左列统计 ---- */
#result-right-col {
  display: flex;
  flex-direction: column;
  gap: 0;
}
/* 会员档案卡取内容高度，不被 flex 拉伸，消除与 chatbot 的空白 */
#result-right-col > .block:first-child {
  flex: 0 0 auto !important;
  margin-bottom: 0 !important;
}
#result-right-col > .block:first-child .dfs-card {
  margin-bottom: 0 !important;
}
#chatbot {
  flex: 1;
  min-height: 0;
  height: auto !important;
  margin-top: 0 !important;
  display: flex;
  flex-direction: column;
}
#chatbot .wrapper {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
#chatbot .bubble-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* ---- 三个内容框统一浅绿底色（同一色系） ---- */
/* 覆盖 Gradio 的 --block-background-fill 变量，让 .block 背景变为浅绿 */
#paths_display,
#paths_display .cm-editor {
  --block-background-fill: #F8FBFA !important;
  background: #F8FBFA !important;
}
#result-left-col > .form,
#result-left-col > .form fieldset {
  --block-background-fill: #F8FBFA !important;
  background: #F8FBFA !important;
}
#chatbot,
#chatbot .bubble-wrap {
  --block-background-fill: #F8FBFA !important;
  background: #F8FBFA !important;
}

/* ---- 闭环评测 Tab ---- */
.loop-input {
  font-size: 13px;
  color: #41524A;
  background: #EDF6F1;
  border: 1px solid #D3E7DC;
  border-radius: 10px;
  padding: 8px 12px;
}
.loop-hint {
  font-size: 13px;
  color: #6B7F75;
  background: #F7FAF8;
  border: 1px dashed #CFE0D7;
  border-radius: 10px;
  padding: 10px 12px;
}
.loop-panel {
  border: 1px solid #DCE9E2;
  border-radius: 12px;
  background: #F8FBFA;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.loop-panel-title {
  font-weight: 600;
  color: #12402F;
  margin-bottom: 8px;
  font-size: 13.5px;
}
.loop-kv {
  display: flex;
  gap: 10px;
  margin: 6px 0;
  font-size: 13px;
  align-items: flex-start;
}
.loop-kv > b {
  flex: 0 0 64px;
  color: #2E7D5B;
  font-weight: 600;
}
.loop-task {
  color: #1F2A25;
  line-height: 1.5;
}
.loop-member {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #12402F;
}
.loop-chip {
  display: inline-block;
  padding: 1px 8px;
  margin: 2px 4px 2px 0;
  border-radius: 999px;
  background: #E3F1EA;
  color: #1E6B4E;
  font-size: 12px;
}
.loop-chip-kn {
  background: #FFF3D6;
  color: #8A5B00;
}
.loop-acc {
  margin: 0;
  padding-left: 18px;
  color: #41524A;
  font-size: 12.5px;
}
.loop-step {
  border-left: 2px solid #CDE3D8;
  padding: 6px 0 8px 12px;
  margin-left: 4px;
}
.loop-step-head {
  font-size: 12px;
  color: #2E7D5B;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.loop-step-no {
  background: #2E7D5B;
  color: #fff;
  border-radius: 50%;
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
}
.loop-thought {
  font-size: 13px;
  color: #33443C;
  margin: 4px 0;
  white-space: pre-wrap;
}
.loop-action {
  font-size: 12.5px;
  color: #12402F;
}
.loop-action code {
  background: #E3F1EA;
  padding: 1px 6px;
  border-radius: 6px;
}
.loop-obs {
  margin: 4px 0 0;
  font-size: 12px;
}
.loop-obs summary {
  cursor: pointer;
  color: #5C6F66;
}
.loop-obs pre {
  background: #F1F6F3;
  border-radius: 8px;
  padding: 8px;
  margin: 6px 0 0;
  max-height: 220px;
  overflow: auto;
  font-size: 11.5px;
}
.loop-answer {
  margin-top: 10px;
  border: 1px dashed #B9D8C9;
  border-radius: 10px;
  padding: 10px 12px;
  background: #FFFFFF;
}
.loop-answer-title {
  font-size: 12px;
  color: #2E7D5B;
  font-weight: 600;
  margin-bottom: 4px;
}
.loop-answer-body {
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: #1F2A25;
}
.loop-score-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.loop-score {
  font-size: 14px;
  color: #41524A;
}
.loop-score b {
  font-size: 20px;
  color: #12402F;
}
.loop-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
}
.loop-badge.ok { background: #DDF3E7; color: #146C43; }
.loop-badge.bad { background: #FDE2E1; color: #B42318; }
.loop-badge.warn { background: #FFF3D6; color: #8A5B00; }
.loop-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.loop-metric {
  background: #FFFFFF;
  border: 1px solid #E1EEE7;
  border-radius: 10px;
  padding: 8px 10px;
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  color: #41524A;
}
.loop-metric b { color: #12402F; }
.loop-meta {
  margin-top: 8px;
  font-size: 12px;
  color: #6B7F75;
}
.loop-empty {
  font-size: 13px;
  color: #8B9A93;
}
.loop-error {
  background: #FDF1F0;
  border-color: #F3C7C3;
  color: #B42318;
}
"""

BANNER_HTML = """
<div class="dfs-banner">
  <div class="dfs-banner-title">🧋 奶茶店会员回访 · 多轮对话合成 Demo</div>
  <div class="dfs-banner-sub">
    Excel 话术模板 + 概率转移矩阵 + FSM 路径生成 → 可复现、可追踪的 SFT 多轮对话数据
  </div>
  <div class="dfs-banner-tags">
    <span class="dfs-tag">📊 配置驱动</span>
    <span class="dfs-tag">🔀 概率矩阵 FSM</span>
    <span class="dfs-tag">🔗 继承链</span>
    <span class="dfs-tag">🎲 固定种子可复现</span>
    <span class="dfs-tag">🧪 虚构数据</span>
  </div>
</div>
"""


def build_nav_html():
    links = [
        ("🏠 项目主页", REPO_URL),
        ("🤗 Live Demo", SPACE_URL),
        ("🏗️ 架构文档", f"{REPO_URL}/blob/main/docs/architecture.md"),
        ("🗺️ Roadmap", f"{REPO_URL}#roadmap"),
    ]
    items = "".join(
        f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'
        for label, url in links
    )
    return f'<div class="dfs-nav">{items}</div>'


# ============================================================
# 编排函数（精简版 main.py，单进程、无断点续传/分析/去重）
# ============================================================

def run_generation(num_dialogues: int, seed: int):
    """
    生成 num_dialogues 条多轮对话。
    返回 (all_dialogues, paths, config_summary)
    """
    # 1. 加载配置
    config = load_config(CONFIG_PATH)

    # 覆盖数量和种子
    config_dict = config.to_dict()
    config_dict["num_paths"] = num_dialogues
    config_dict["num_dialogues"] = num_dialogues
    config_dict["num_paths_to_generate"] = num_dialogues
    config_dict["random_seed"] = seed
    config = type(config)(config_dict)  # 重建 Config

    # 2. 加载 prob → modules
    prob_df, modules = load_prob_matrix(config.get("prob_path"))
    config = sync_config_from_prob(config, modules)

    # 3. 随机服务
    rng = RandomService(seed)

    # 4. 加载 Excel 话术
    excel_path = config.get("excel_path")
    df_dict = load_sheets(excel_path, modules)

    # 5. 促销话术 sheet
    pressure_sheet_name = config.get("pressure_sheet_name", "链接促销话术")
    try:
        pressure_df = pd.read_excel(excel_path, sheet_name=pressure_sheet_name)
    except ValueError:
        pressure_df = pd.DataFrame()

    # 6. 案例加载
    time_gen = create_time_generator(config)
    case_loader = create_case_loader(config)
    cases, prompts = case_loader.load(rng=rng, time_gen=time_gen)

    # 7. 路径生成
    path_gen = PathGenerator(config, prob_df, rng)
    all_paths = path_gen.generate(num_dialogues, seed, cache_path=None)

    # 8. 对话构建
    pressure_manager = PressureManager(pressure_df, rng, config)
    builder = DialogueBuilder(config, df_dict, rng, pressure_manager)

    dialogues = []
    for i, path in enumerate(all_paths):
        case = cases[i % len(cases)]
        prompt = prompts[i % len(cases)]
        messages = builder.build(path, case, prompt)
        dialogues.append({
            "dialogue_id": i + 1,
            "path": path,
            "case_file": case.get("_filename", f"case_{i+1:03d}"),
            "case_info": _extract_case_info(case),
            "messages": [
                {"role": m["role"], "content": m["content"]}
                for m in messages
            ],
        })

    # 配置摘要
    config_summary = {
        "modules": modules,
        "a_set": config.get("a_set", []),
        "b_set": config.get("b_set", []),
        "terminal_modules": config.get("terminal_modules", []),
        "self_loop_modules": config.get("self_loop_modules", {}),
        "start_module": config.get("start_module"),
        "num_dialogues": num_dialogues,
        "seed": seed,
    }

    return dialogues, all_paths, config_summary


# 案例信息卡展示的字段（按展示顺序）
_CARD_FIELDS = [
    "门店名称", "客户姓名", "会员等级", "积分余额",
    "消费金额", "到期日期", "门店电话", "小程序名称",
]


def _extract_case_info(case):
    """从 case dict 中提取用于界面展示的字段"""
    info = {}
    for f in _CARD_FIELDS:
        v = case.get(f)
        if v is not None and str(v).strip():
            info[f] = str(v).strip()
    return info


# ============================================================
# 渲染辅助
# ============================================================

def _prob_heatmap_html(prob_df):
    """把概率矩阵渲染成带色阶的 HTML 表格（值越大绿色越深）"""
    mods = [str(m) for m in prob_df.index]
    parts = ['<div class="dfs-heat"><table class="dfs-heat-table"><thead><tr><th></th>']
    for c in mods:
        parts.append(f"<th>{c}</th>")
    parts.append("</tr></thead><tbody>")
    for r in mods:
        parts.append(f'<tr><th class="rowh">{r}</th>')
        for c in mods:
            try:
                v = float(prob_df.loc[r, c]) * 100
            except (KeyError, TypeError, ValueError):
                v = 0.0
            if v <= 0:
                bg, color = "transparent", "#CBD5E1"
                text = "·"
            else:
                alpha = min(0.12 + (v / 100.0) * 0.88, 1.0)
                bg = f"rgba(46, 125, 91, {alpha:.3f})"
                color = "#FFFFFF" if alpha > 0.42 else "#12402F"
                text = f"{v:.0f}"
            parts.append(
                f'<td style="background:{bg};color:{color}">{text}</td>'
            )
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _case_card_html(case_info, dialogue_id=None, case_file=None):
    if not case_info:
        return ""
    items = "".join(
        f'<div class="dfs-card-item"><b>{k}</b>：{v}</div>'
        for k, v in case_info.items()
    )
    head = "会员档案"
    if dialogue_id is not None:
        head = f"会员档案 · 对话 {dialogue_id}"
        if case_file:
            head += f"（{case_file}）"
    return (
        f'<div class="dfs-card">'
        f'<div class="dfs-card-title">🪪 {head}</div>'
        f'<div class="dfs-card-grid">{items}</div>'
        f"</div>"
    )


def _dialogue_to_chatbot(dialogue):
    """将对话消息转为 gr.Chatbot messages 格式"""
    msgs = []
    for m in dialogue["messages"]:
        role = m["role"]
        content = m["content"]
        if role == "system":
            # system 消息作为 assistant 展示（带视觉标记）
            msgs.append({
                "role": "assistant",
                "content": f"📋 **[System Prompt]**\n\n{content}",
            })
        elif role == "user":
            msgs.append({"role": "user", "content": content})
        elif role == "assistant":
            msgs.append({"role": "assistant", "content": content})
    return msgs


def _stats_html(dialogues):
    """生成统计条 HTML"""
    n = len(dialogues)
    if n == 0:
        return ""
    turns = [sum(1 for m in d["messages"] if m["role"] != "system") for d in dialogues]
    avg_turns = sum(turns) / n
    uniq_paths = len({tuple(d["path"]) for d in dialogues})
    cards = [
        ("生成对话", n),
        ("平均轮数", f"{avg_turns:.1f}"),
        ("不同路径", uniq_paths),
    ]
    items = "".join(
        f'<div class="dfs-stat">{label} <b>{val}</b></div>' for label, val in cards
    )
    return f'<div class="dfs-stats">{items}</div>'


# ============================================================
# Gradio 回调函数
# ============================================================

def on_generate(num_dialogues, seed, progress=gr.Progress()):
    """生成按钮回调"""
    try:
        progress(0.15, desc="加载配置与概率矩阵…")
        dialogues, paths, summary = run_generation(num_dialogues, seed)
        progress(1.0, desc="完成")
    except Exception as e:
        logger.error(f"生成失败: {e}", exc_info=True)
        empty_update = gr.update(choices=[], value=None)
        return (
            [], json.dumps({"error": str(e)}), f"生成失败: {e}",
            empty_update, gr.update(visible=False), "", "",
        )

    # 路径展示（纯文本，每条路径独占一行）
    paths_text = "\n".join(
        f"路径 {i+1:>2} [{d['case_file']}]  {' → '.join(d['path'])}"
        for i, d in enumerate(dialogues)
    )

    # JSON 下载
    json_str = json.dumps(dialogues, ensure_ascii=False, indent=2)

    # 选择器选项
    choices = [f"对话 {i+1} ({d['case_file']})" for i, d in enumerate(dialogues)]
    default_choice = choices[0] if choices else None

    # 默认展示第一个对话
    first = dialogues[0] if dialogues else None
    chatbot_msgs = _dialogue_to_chatbot(first) if first else []
    case_card = _case_card_html(
        first["case_info"], first["dialogue_id"], first["case_file"]
    ) if first else ""

    return (
        chatbot_msgs, json_str, paths_text,
        gr.update(choices=choices, value=default_choice),
        gr.update(visible=True),
        case_card, _stats_html(dialogues),
    )


def on_select_dialogue(selected_value, dialogues_json):
    """选择对话回调（从 Radio label 解析索引）"""
    if not selected_value or not dialogues_json:
        return [], ""
    import re

    m = re.search(r"对话 (\d+)", selected_value)
    if not m:
        return [], ""
    idx = int(m.group(1)) - 1
    dialogues = json.loads(dialogues_json)
    if 0 <= idx < len(dialogues):
        d = dialogues[idx]
        return (
            _dialogue_to_chatbot(d),
            _case_card_html(d["case_info"], d["dialogue_id"], d["case_file"]),
        )
    return [], ""


def _pick_dialogue(selected_value, dialogues_json):
    """从选择器 label 解析索引，返回对应 dialogue dict；无效则 None。"""
    if not selected_value or not dialogues_json:
        return None
    import re

    m = re.search(r"对话 (\d+)", selected_value)
    if not m:
        return None
    idx = int(m.group(1)) - 1
    try:
        dialogues = json.loads(dialogues_json)
    except (TypeError, ValueError):
        return None
    if 0 <= idx < len(dialogues):
        return dialogues[idx]
    return None


def on_loop_input_change(selected_value, dialogues_json):
    """Tab2 顶部「当前输入」随 Tab1 选择变化。"""
    return loop_demo.render_input_header(_pick_dialogue(selected_value, dialogues_json))


def on_run_loop(selected_value, dialogues_json, mode, use_judge, progress=gr.Progress()):
    """运行一次闭环：回流转换 → 注入会员 → Agent 执行 → 评测。"""
    dialogue = _pick_dialogue(selected_value, dialogues_json)
    if not dialogue:
        return loop_demo.render_input_header(None), "", "", "", ""

    header = loop_demo.render_input_header(dialogue)
    try:
        result = loop_demo.run_closed_loop(
            dialogue,
            mode=mode,
            use_llm_judge=use_judge,
            on_stage=lambda msg, frac: progress(frac, desc=msg),
        )
    except Exception as e:
        logger.error(f"闭环执行失败: {e}", exc_info=True)
        return header, loop_demo.render_error_html(str(e)), "", "", ""

    ctx = result["context"]
    judge_label = "LLM 裁判" if (mode == "真实" and use_judge) else "规则判定"
    return (
        header,
        loop_demo.render_case_html(ctx["case"], ctx["case_file"]),
        loop_demo.render_evalcase_html(result),
        loop_demo.render_metrics_html(result["record"], judge_label),
        loop_demo.render_trace_html(result["record"]),
    )


def load_config_summary():
    """加载配置摘要用于界面展示"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    prob_df, modules = load_prob_matrix(config["prob_path"])
    return config, prob_df, modules


# ============================================================
# Gradio 界面
# ============================================================

def create_demo():
    config, prob_df, modules = load_config_summary()
    real_model_available = loop_demo.has_api_key()
    mode_choices = ["基线", "真实"] if real_model_available else ["基线"]

    with gr.Blocks(title="奶茶店会员回访 Demo") as demo:
        # ---- Banner + 导航 ----
        gr.HTML(BANNER_HTML)
        gr.HTML(build_nav_html())

        with gr.Tabs():
            # ============================================================
            # Tab 1：数据生成
            # ============================================================
            with gr.Tab("📊 数据生成"):
                gr.Markdown(
                    """
                    本 Demo 展示 **dialog-sft-forge** 框架的端到端能力：
                    话术模板（Excel）+ 概率转移矩阵 → FSM 随机路径 → 多轮对话合成。
                    场景为完全虚构的「茗香茶饮」会员回访，所有数据由脚本生成、固定种子可复现。
                    """
                )

                # ---- 配置预览 ----
                with gr.Accordion("🔧 配置预览", open=False):
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown(f"""
                            **模块列表**（{len(modules)} 个）

                            {' · '.join(modules)}

                            ---

                            - **起始模块**：`{config.get('start_module')}`
                            - **A 集**（路径中仅出现一个）：{config.get('a_set', [])}
                            - **B 集**（可重复出现）：{config.get('b_set', [])}
                            - **终止模块**：{config.get('terminal_modules', [])}
                            - **自循环模块**：{config.get('self_loop_modules', {})}
                            - **促销话术插入模块**：{config.get('insert_nodes', [])}
                            """)
                        with gr.Column(scale=2):
                            gr.HTML(
                                "<div class='dfs-chat-hint'>概率转移矩阵（%，绿色深浅 = 转移概率高低，· 表示无转移）</div>"
                                + _prob_heatmap_html(prob_df)
                            )

                # ---- 生成控制 ----
                with gr.Row():
                    num_slider = gr.Slider(
                        minimum=1, maximum=20, value=5, step=1,
                        label="🎯 生成对话数",
                    )
                    seed_input = gr.Number(
                        value=42, label="🎲 随机种子",
                        info="相同种子 + 相同数量 → 完全一致的输出",
                    )
                    generate_btn = gr.Button("🚀 生成对话", variant="primary", scale=1)

                # ---- 结果展示 ----
                dialogue_state = gr.State()  # 存储完整 dialogues JSON 字符串

                with gr.Row(visible=False, equal_height=True) as result_row:
                    with gr.Column(scale=1, elem_id="result-left-col"):
                        paths_display = gr.Code(
                            label="🗺️ 生成路径（每行一条）",
                            interactive=False,
                            lines=1,
                            max_lines=1,
                            wrap_lines=True,
                            elem_id="paths_display",
                        )
                        dialogue_selector = gr.Radio(
                            label="💬 选择对话查看",
                            choices=[],
                            elem_id="dialogue_selector",
                        )
                        download_btn = gr.DownloadButton("📥 下载 JSON")
                        stats_html = gr.HTML()
                    with gr.Column(scale=2, elem_id="result-right-col"):
                        case_card = gr.HTML()
                        chatbot = gr.Chatbot(
                            label="多轮对话",
                            height=None,
                            elem_id="chatbot",
                        )

            # ============================================================
            # Tab 2：闭环评测（生成对话 → 回流 → Agent → 评测）
            # ============================================================
            with gr.Tab("🔁 闭环评测"):
                gr.Markdown(
                    """
                    **闭环：** 取「数据生成」页当前选中的对话 → 回流成 EvalCase（注入运行时会员）
                    → ReAct Agent 带着工具执行 → 规则 / LLM 双裁判打分。
                    """
                )
                loop_input_html = gr.HTML(loop_demo.render_input_header(None))

                with gr.Row():
                    loop_mode = gr.Radio(
                        choices=mode_choices,
                        value="基线",
                        label="🤖 执行模式",
                        scale=2,
                        info=("基线 = FakeLLM 全对脚本，秒级返回"
                              if real_model_available
                              else "未检测到 AGENT_API_KEY，仅支持规则基线"),
                    )
                    loop_judge = gr.Checkbox(
                        label="启用 LLM 裁判（叠加质量分）",
                        value=False,
                        scale=2,
                    )
                    loop_run_btn = gr.Button("▶ 运行闭环", variant="primary", scale=1)

                with gr.Row(equal_height=True):
                    with gr.Column(scale=1):
                        loop_case_html = gr.HTML()
                        loop_eval_html = gr.HTML()
                    with gr.Column(scale=2):
                        loop_metrics_html = gr.HTML()
                        loop_trace_html = gr.HTML()

        # ---- 事件绑定 ----
        generate_btn.click(
            fn=on_generate,
            inputs=[num_slider, seed_input],
            outputs=[
                chatbot, dialogue_state, paths_display,
                dialogue_selector, result_row, case_card, stats_html,
            ],
        ).then(
            fn=on_loop_input_change,
            inputs=[dialogue_selector, dialogue_state],
            outputs=[loop_input_html],
        )

        dialogue_selector.change(
            fn=on_select_dialogue,
            inputs=[dialogue_selector, dialogue_state],
            outputs=[chatbot, case_card],
        )
        dialogue_selector.change(
            fn=on_loop_input_change,
            inputs=[dialogue_selector, dialogue_state],
            outputs=[loop_input_html],
        )

        # 闭环运行
        loop_run_btn.click(
            fn=on_run_loop,
            inputs=[dialogue_selector, dialogue_state, loop_mode, loop_judge],
            outputs=[
                loop_input_html, loop_case_html, loop_eval_html,
                loop_metrics_html, loop_trace_html,
            ],
        )

        # JSON 下载（动态生成文件）
        def _make_json_file(json_str):
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            tmp.write(json_str)
            tmp.close()
            return tmp.name

        download_btn.click(
            fn=_make_json_file,
            inputs=[dialogue_state],
            outputs=[download_btn],
        )

    return demo


# ============================================================
# 入口
# ============================================================

demo = create_demo()


def launch_demo(**kwargs):
    """启动 Demo（统一在这里应用主题与自定义 CSS）"""
    demo.launch(theme=create_theme(), css=CSS, **kwargs)


if __name__ == "__main__":
    launch_demo()
