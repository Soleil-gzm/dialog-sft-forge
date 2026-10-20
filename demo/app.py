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

/* ---- 结果区右列：chatbot 填满剩余空间并内部滚动 ---- */
#result-right-col {
  display: flex;
  flex-direction: column;
}
#chatbot {
  flex: 1;
  min-height: 0;
  height: auto !important;
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

    with gr.Blocks(title="奶茶店会员回访 Demo") as demo:
        # ---- Banner + 导航 ----
        gr.HTML(BANNER_HTML)
        gr.HTML(build_nav_html())
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

        # ---- 事件绑定 ----
        generate_btn.click(
            fn=on_generate,
            inputs=[num_slider, seed_input],
            outputs=[
                chatbot, dialogue_state, paths_display,
                dialogue_selector, result_row, case_card, stats_html,
            ],
        )

        dialogue_selector.change(
            fn=on_select_dialogue,
            inputs=[dialogue_selector, dialogue_state],
            outputs=[chatbot, case_card],
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
