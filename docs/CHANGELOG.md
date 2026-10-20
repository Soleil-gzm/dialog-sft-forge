# 变更记录

本文件记录仓库中可验证的用户可见变更。项目此前没有统一维护此文件，因此不对无法核实的历史版本作追溯性补写。

## [Unreleased]

### 新增

- M3 Agent Eval 离线评测模块（`agent/eval/`）：手写 YAML 评测集、六项规则指标、`Judge` 裁判抽象（默认规则判定，LLM 裁判预留）、FakeLLM 无 Key 基线、版本化报告（report.md/json、cases.json、failures/）。
- `agent/run_eval.py` 命令行入口：`--config/--testset/--output-dir/--limit/--seed/--mock/--use-llm-judge`，输出到 `output/eval/{时间戳}/`。
- 评测相关单元测试 4 个文件，共 27 个用例。

### 文档

- 建立架构、项目设计、进度、变更记录和工作日志五份项目文档。
- README 文档导航覆盖上述文档，并明确当前实现与后续路线的边界。
- 修正 Demo 配置文件路径为 `demo/config/demo_config.yaml`。
- 补充 Windows PowerShell 虚拟环境激活和 Agent API Key 设置示例。
- 说明 Embedding 未配置时 RAG 检索退化为 BM25 单路。
- 标明 Agent 运行轨迹使用虚构模拟数据，不代表生产系统结果。

### 当前能力基线

以下为当前仓库能力索引，不代表这些能力均在本次变更中新增：

- 配置驱动的多轮对话生成，包含概率路径、条件解析、话术组装及批量任务支持。
- 奶茶店会员回访 Agent 原型，包含 ReAct、工具注册、短期记忆、业务工具和知识工具。
- BM25 与可选向量检索、RRF 排序融合及检索出处信息。
- 生成器、Agent、知识工具与 RAG 的自动化测试和 Agent 轨迹示例。

### 未纳入当前版本

- 自动化 Agent 评测平台、Xtuner 训练脚本/权重、生产级向量数据库、清洗增强集成及轨迹回流闭环。

## 版本说明

Python 包版本以 `pyproject.toml` 为准。发布正式版本时，应将已验证的 Unreleased 条目归档到对应版本，并记录兼容性变化和迁移说明。