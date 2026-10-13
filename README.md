---
title: Dialog SFT Forge
emoji: 🧋
colorFrom: green
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
license: mit
---

# Dialog SFT Forge — 从 0 到 1 的对话 SFT 数据闭环

配置驱动的多轮对话合成与微调数据工厂：以「奶茶店会员回访」为示例场景，覆盖
**数据合成 → 清洗 → SFT 微调 → 评估 → 部署** 的完整闭环。所有数据均为脚本生成的虚拟数据（固定种子、可复现），不含任何真实业务信息。

## 流水线总览

| 阶段 | 模块 | 说明 | 状态 |
|------|------|------|------|
| 1. 数据合成 | `scripts_general/` | 概率矩阵 FSM 采样对话路径 + 模块话术继承链 + 占位符填充，批量产出多轮对话 JSONL | ✅ |
| 2. 数据清洗 | `cleaning/` | 质量过滤、去重、格式规整 | 🚧 Planned |
| 3. SFT 微调 | `training/` | 对接主流训练框架的 SFT 训练脚本 | 🚧 Planned |
| 4. 评估对比 | `evaluation/` | 微调前后模型效果对比评估 | 🚧 Planned |
| 5. 部署演示 | `demo/` | Gradio 在线体验（可一键部署到 HuggingFace Spaces） | ✅ |

## 快速开始

```bash
pip install -r requirements.txt

# 1) 生成 demo 虚拟数据（固定种子可复现）：
#    15 模块话术模板 / 概率矩阵（由模块图自动派生）/ 500 个案例 / 500 个配对 system prompt
python demo/generate_demo_data.py

# 2) 批量合成 5000 条对话（split 加载器：案例与 prompt 分离）
python scripts_general/main.py -c demo/demo_config.yaml
# 输出：output/<task_name>_5000_<seed>/*.json

# 3) 启动 Gradio 演示界面
python demo/app.py
```

自定义场景只需三步：

1. 写案例文件（`- 字段：值` 逐行格式）；
2. 写话术模板 Excel（模块 sheet + 概率矩阵 sheet，支持 `{字段}` 占位符与 `&` 组合条件）；
3. 复制 `demo/demo_config.yaml` 改路径与模块名。

## 架构特点

- **配置驱动**：模块、概率矩阵、促销/终止策略全部来自 Excel + YAML，换场景不改代码
- **概率矩阵 FSM**：以模块转移概率矩阵做加权采样，`start/a_set/b_set/terminal/self_loop` 约束路径合法性
- **条件注册表**：原子条件（数值比较 / 字段空非空）+ `&` 复合解析，新增条件类型只需注册一个子类
- **话术继承链**：`parent(继承)` 祖先/后代链 + `flexible_stop` 概率截断，模块内多轮自然展开
- **工程化生成**：单/多进程统一路径、断点续传、流式写入、trace 追踪、相邻对话去重
- **可复现**：全局固定随机种子，同配置同输出

## Roadmap

- [ ] 阶段 2：数据清洗（`cleaning/`）— 质量过滤、相似度去重、训练格式转换
- [ ] 阶段 3：SFT 微调（`training/`）— LoRA/全参训练脚本与配置
- [ ] 阶段 4：评估对比（`evaluation/`）— 自动指标 + 人工评估面板
- [ ] 阶段 5：服务化（`serving/`）— 推理 API 与在线对话演示

## License

MIT
