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
# ============================================================
DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DEMO_DIR)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts_general")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, DEMO_DIR)  # 为了 import generate_demo_data

# ============================================================
# 自动生成 demo 数据（如果缺失）
# ============================================================
DATA_DIR = os.path.join(DEMO_DIR, "data")
CONFIG_PATH = os.path.join(DEMO_DIR, "demo_config.yaml")


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


# ============================================================
# Gradio 回调函数
# ============================================================

def on_generate(num_dialogues, seed):
    """生成按钮回调：返回 (chatbot_messages, json_str, paths_display, selector_choices, selector_update)"""
    try:
        dialogues, paths, summary = run_generation(num_dialogues, seed)
    except Exception as e:
        logger.error(f"生成失败: {e}", exc_info=True)
        return [], json.dumps({"error": str(e)}), f"生成失败: {e}", gr.update(choices=[], value=None), gr.update(visible=False)

    # 路径展示
    paths_text = "\n".join(
        f"**路径 {i+1}** ({d['case_file']}): {' → '.join(d['path'])}"
        for i, d in enumerate(dialogues)
    )

    # JSON 下载
    json_str = json.dumps(dialogues, ensure_ascii=False, indent=2)

    # 选择器选项
    choices = [f"对话 {i+1} ({d['case_file']})" for i, d in enumerate(dialogues)]
    default_choice = choices[0] if choices else None

    # 默认展示第一个对话
    chatbot_msgs = _dialogue_to_chatbot(dialogues[0]) if dialogues else []

    return chatbot_msgs, json_str, paths_text, gr.update(choices=choices, value=default_choice), gr.update(visible=True)


def on_select_dialogue(selected_value, dialogues_json):
    """选择对话回调（从 Radio label 解析索引）"""
    if not selected_value or not dialogues_json:
        return []
    import re

    m = re.search(r"对话 (\d+)", selected_value)
    if not m:
        return []
    idx = int(m.group(1)) - 1
    dialogues = json.loads(dialogues_json)
    if 0 <= idx < len(dialogues):
        return _dialogue_to_chatbot(dialogues[idx])
    return []


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
        # ---- 标题 ----
        gr.Markdown("""
        # 奶茶店会员回访 — 多轮对话合成 Demo

        本 Demo 展示了 **dialog-sft-forge** 框架的核心能力：
        从话术模板（Excel）+ 概率转移矩阵 → 随机路径生成 → 多轮对话合成。

        场景为完全虚构的「茗香茶饮」会员回访，所有数据由脚本生成，可复现。
        """)

        # ---- 配置预览 ----
        with gr.Accordion("配置预览", open=False):
            gr.Markdown(f"""
            **模块列表** ({len(modules)} 个): {' / '.join(modules)}

            - **起始模块**: {config.get('start_module')}
            - **A 集** (路径中仅出现一个): {config.get('a_set', [])}
            - **B 集** (可重复出现): {config.get('b_set', [])}
            - **终止模块**: {config.get('terminal_modules', [])}
            - **自循环模块**: {config.get('self_loop_modules', {})}
            - **促销话术插入模块**: {config.get('insert_nodes', [])}
            """)
            gr.Dataframe(
                value=prob_df * 100,  # 显示百分比
                label="概率转移矩阵（%）",
                interactive=False,
            )

        # ---- 生成控制 ----
        with gr.Row():
            num_slider = gr.Slider(
                minimum=1, maximum=20, value=5, step=1,
                label="生成对话数",
            )
            seed_input = gr.Number(
                value=42, label="随机种子",
                info="相同种子+相同数量 → 完全一致的输出",
            )
            generate_btn = gr.Button("🚀 生成对话", variant="primary")

        # ---- 结果展示 ----
        dialogue_state = gr.State()  # 存储完整 dialogues JSON 字符串

        with gr.Row(visible=False) as result_row:
            with gr.Column(scale=1):
                paths_display = gr.Markdown(label="生成路径")
                dialogue_selector = gr.Radio(
                    label="选择对话查看",
                    choices=[],
                )
                download_btn = gr.DownloadButton("📥 下载 JSON")
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    label="多轮对话",
                    height=500,
                )

        # ---- 事件绑定 ----
        # 生成
        generate_btn.click(
            fn=on_generate,
            inputs=[num_slider, seed_input],
            outputs=[chatbot, dialogue_state, paths_display, dialogue_selector, result_row],
        )

        # 选择对话
        dialogue_selector.change(
            fn=on_select_dialogue,
            inputs=[dialogue_selector, dialogue_state],
            outputs=[chatbot],
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

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft())
