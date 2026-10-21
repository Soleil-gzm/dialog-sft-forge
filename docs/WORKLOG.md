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

### 后续补充：真实 API 冒烟与 max_steps 校准（同日）

- 用真实 DeepSeek（deepseek-v4-flash，max_steps=6）跑完整评测：7 条通过 5 条（71.4%）。5 项指标全绿（工具覆盖/政策引用/禁止编造/健壮性），仅「任务完成」0.714。
- 失败 2 条均为「调用齐工具后在 6 步内未及输出最终答复被截断」（轨迹正确，如 eval_normal_followup 已完成 log_visit_result）。
- 将 agent_config.yaml 的 `react.max_steps` 6→10 后重跑：7/7 通过，平均总分 0.976。
- 报告：`output/eval/20261021_224646/`（改前）、`output/eval/20261021_225151/`（改后）。

### 后续补充：扩充评测集至 12 条（同日）

- testset.yaml 由 7 条扩至 12 条，新增覆盖：消费偏好推荐（基于真实消费记录）、VIP 配送免配送费、退款时优惠券/积分处理、积分与优惠券能否并用（歧义政策）、缺货替代推荐；涉及 service.md 这一此前未覆盖的知识源。
- 更新 test_eval_cases.py 数量断言 7→12。
- 验证：mock 全量 12/12（总分 0.982）；真实 DeepSeek 12/12（总分 0.9764），六项指标均值全绿。
- 报告：`output/eval/20261021_225936/`（mock）、`output/eval/20261021_225946/`（真实）。

### 后续补充：启用 LLM 裁判对比规则分（同日）

- 启用 `--use-llm-judge` 的 LLMJudge（每条用例在规则分基础上追加一次裁判 LLM 的质量分）。
- report.py 逐用例表新增「LLM质量分」列，与规则总分并列展示；rule-only 时该列显示 `-`。
- 真实 DeepSeek 评测：12/12 通过（平均总分 0.9768）。规则总分与 LLM 质量分高度一致，仅 3 条用例质量分略低于 1.0：eval_out_of_stock（0.8）、eval_purchase_preference（0.8）、eval_out_stock_alternative（0.98），多为裁判对「未直接点明替代/未充分展开消费偏好」的微观评分，不改变通过判定。
- 报告：`output/eval/20261021_230744/`。  

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