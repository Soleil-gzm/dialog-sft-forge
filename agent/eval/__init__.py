"""Agent Eval 评测模块（M3）。

离线评测：
  1. 从手写 YAML 评测集加载用例（case_schema）
  2. 逐用例驱动 ReActAgent 运行，记录 trace（runner）
  3. 按规则指标打分（metrics + judge），输出版本化报告（report）
"""
