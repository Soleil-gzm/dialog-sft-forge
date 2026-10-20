# 工作日志

本日志记录有日期、范围和结果的研发及维护活动。历史条目只在有可核实依据时补录。

## 2026-10-21：M3 Agent Eval 离线评测模块

**范围：** agent/eval/ 评测模块（评测集、规则指标、裁判抽象、运行器、报告）与 agent/run_eval.py 命令行。

**完成事项：**

- 新增 `agent/eval/case_schema.py`：`EvalCase` 数据模型与 `load_testset()`，含字段白名单与必填校验。
- 新增 `agent/eval/testset.yaml`：7 条手写评测用例（常规回访、积分到期提醒、优惠推荐、会员不存在、缺货商品、积分抵扣规则、历史回访召回）。
- 新增 `agent/eval/metrics.py`：六项规则指标（工具覆盖/任务完成/健壮性/政策引用/禁止编造/效率）与加权总分、通过判定；领域错误与执行级崩溃分开计分。
- 新增 `agent/eval/judge.py`：`Judge` 抽象、`RuleBasedJudge`（默认）与预留的 `LLMJudge`（`--use-llm-judge` 开关，默认关闭）。
- 新增 `agent/eval/fake_llm.py`：`FakeLLM` 与 `tool_call`，支持无 API Key 的 CI 基线与单元测试注入。
- 新增 `agent/eval/runner.py`：逐用例驱动 `ReActAgent` 运行并打分，支持 limit/seed 抽样与 mock 模式。
- 新增 `agent/eval/report.py`：输出 report.md / report.json / cases.json / failures/{case_id}.json 的版本化报告。
- 新增 `agent/run_eval.py`：CLI 入口（`--config/--testset/--output-dir/--limit/--seed/--mock/--use-llm-judge`），输出到 `output/eval/{时间戳}/`。
- `tests/conftest.py` 增加项目根目录到 sys.path，使 `import agent.*` 可用。
- 新增 4 个测试文件（case_schema、metrics、report、runner），共 27 个评测相关用例。

**验证：**

- `python -m pytest tests/`：51 项全部通过（含原有生成器/Agent 测试）。
- `python agent/run_eval.py --mock`：7 条用例全部通过，平均总分 0.97；报告输出到 `output/eval/20261021_012100/`。

**风险/后续：**

- 规则判定为近似：政策引用按「依据：」标注、禁止编造按 observation 回填、健壮性按注册表错误标记计分；LLM 裁判预留未启用。
- 未跑真实 API Key 评测，评测集对真实模型行为的覆盖待验证；下一步建议用真实模型冒烟一次并扩充用例。  

## 2026-10-17：项目文档基线整理

**范围：** README、系统架构、项目设计、进度、变更与工作日志。  
**依据：** 仓库目录、入口脚本、配置文件、Agent/RAG 实现、测试目录和现有项目方案材料。

**完成事项：**

- 梳理数据生成器、Agent 与 RAG 的当前模块边界及运行链路。
- 将已实现能力与 Xtuner、Agent Eval、自动轨迹回流等规划项分开记录。
- 明确当前向量检索为 NumPy 内存实现，未配置 Embedding 服务时退化为 BM25。
- 更新 README 文档导航、Demo 配置路径、Windows PowerShell 环境/API Key 命令，并标明运行轨迹基于虚构模拟数据。
- 新增项目设计、项目进度、变更记录和工作日志文档，并更新架构说明。

**验证：** 内容依据仓库现有代码和配置编写；文档路径及交叉引用应在本次变更后检查。  
**未包含：** 未修改生成器或 Agent 运行时代码，未新增训练、评测或生产部署能力。

## 后续记录模板

后续工作按日期追加，至少记录：

- **范围：** 涉及模块或需求。
- **完成事项：** 代码、配置或文档的可核实变更。
- **验证：** 执行的测试、命令及结果；未验证项也需注明。
- **风险/后续：** 未解决问题、负责人或下一步决策。