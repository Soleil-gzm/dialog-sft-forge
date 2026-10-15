"""奶茶店会员回访 Agent 模块（手搓 ReAct + 工具调用）。

本模块是 dialog-sft-forge 的下游 Agent 能力层：
    数据工厂（scripts_general） → 本模块（工具调用 / 推理循环） → 评估与回流

入口：python agent/run_agent.py
"""
