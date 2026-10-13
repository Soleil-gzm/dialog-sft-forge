#!/usr/bin/env python3
"""
批量任务运行器：读取 base.yaml + tasks.yaml，自动生成数据并执行对话生成。

流程：
  1. 加载 base 配置与任务列表
  2. 对每个 enabled 任务：
     - 深合并任务配置到 base
     - 若 prob_auto_generate.enabled：从 categories.yaml 生成 prob.xlsx
     - 若 case_auto_generate.enabled：从 prompt 模板生成案例 + 配对 prompt
     - 组装运行时配置（main.py 格式），写入临时 yaml
     - 调用 main.run() 执行生成

用法：
    python scripts_general/batch_runner.py -t demo/config/batch/milktea/tasks.yaml
    python scripts_general/batch_runner.py -t demo/config/batch/milktea/tasks.yaml --task "VIP会员回访"
"""

import argparse
import copy
import os
import sys
import tempfile
from typing import Any, Dict

import yaml

# 确保 scripts_general 在 sys.path 中
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.data.case_generator import generate_cases
from core.data.prob_generator import generate_prob_from_categories


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深合并：override 覆盖 base，dict 类型递归合并"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _resolve_start_module(start_module: Any) -> str:
    """start_module 可能是字符串或 {模块: 概率} dict，取最高概率项"""
    if isinstance(start_module, str):
        return start_module
    if isinstance(start_module, dict):
        return max(start_module, key=start_module.get)
    raise ValueError(f"不支持的 start_module 类型: {type(start_module)}")


def _handle_prob_auto_generate(task_cfg: Dict[str, Any]) -> None:
    """若启用 prob 自动生成，从 categories.yaml 生成 prob.xlsx"""
    pag = task_cfg.get("prob_auto_generate", {})
    if not pag.get("enabled"):
        return
    categories_yaml = pag["categories_yaml"]
    output = pag.get("output") or task_cfg.get("prob_path")
    if not output:
        raise ValueError("prob_auto_generate 缺少 output 路径，且 task 未配置 prob_path")
    print(f"  [prob] 从 {categories_yaml} 生成概率矩阵 → {output}")
    generate_prob_from_categories(categories_yaml, output)
    task_cfg["prob_path"] = output


def _handle_case_auto_generate(task_cfg: Dict[str, Any]) -> None:
    """若启用案例自动生成，从 prompt 模板生成案例 + 配对 prompt"""
    cag = task_cfg.get("case_auto_generate", {})
    if not cag.get("enabled"):
        return
    gen_type = cag.get("generator_type", "milktea")
    num_cases = cag.get("num_cases", 500)
    seed = cag.get("seed", task_cfg.get("random_seed", 42))

    # prompt 模板目录：优先用 prompt_dir，否则从 system_path 推导
    prompt_dir = cag.get("prompt_dir")
    if not prompt_dir:
        sys_path = cag.get("prompt_system_path") or "demo/prompt/system.txt"
        prompt_dir = os.path.dirname(sys_path)

    case_loader = task_cfg.setdefault("case_loader", {})
    replace_dir = cag.get("output", {}).get("replace_dir") or case_loader.get("replace_dir")
    system_dir = cag.get("output", {}).get("system_dir") or case_loader.get("system_dir")
    if not replace_dir or not system_dir:
        raise ValueError("case_auto_generate 缺少 replace_dir / system_dir 输出路径")

    force = cag.get("force_regenerate", False)
    if not force and os.path.isdir(replace_dir) and os.listdir(replace_dir):
        print(f"  [case] 目录已存在且非空，跳过生成（force_regenerate=false）: {replace_dir}")
    else:
        print(f"  [case] 生成 {num_cases} 个案例 → {replace_dir} / {system_dir}")
        generate_cases(
            generator_type=gen_type,
            prompt_dir=prompt_dir,
            replace_dir=replace_dir,
            system_dir=system_dir,
            num_cases=num_cases,
            seed=seed,
        )

    # 确保 case_loader 路径指向生成结果
    case_loader.setdefault("type", "split")
    case_loader["replace_dir"] = replace_dir
    case_loader["system_dir"] = system_dir


def _build_runtime_config(task_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """将合并后的任务配置转换为 main.py 运行时配置格式"""
    runtime: Dict[str, Any] = copy.deepcopy(task_cfg)

    # 去除批量任务专属字段
    for key in ("name", "enabled", "base", "prob_auto_generate", "case_auto_generate"):
        runtime.pop(key, None)

    # start_module 规范化
    runtime["start_module"] = _resolve_start_module(runtime.get("start_module"))

    # 对话数量统一
    num_paths = runtime.get("num_paths", runtime.get("num_dialogues", 40000))
    runtime["num_paths"] = num_paths
    runtime["num_dialogues"] = num_paths
    runtime["num_paths_to_generate"] = num_paths

    # 默认 paths_cache（若未配置）
    runtime.setdefault("paths_cache_dir", "paths")
    runtime.setdefault(
        "paths_cache",
        os.path.join(runtime.get("output_dir", "output"), "paths", "all_paths_{num_paths}_{seed}.json"),
    )

    return runtime


def run_tasks(tasks_yaml: str, only_task: str = None) -> None:
    """执行批量任务"""
    tasks_yaml = os.path.abspath(tasks_yaml)
    base_dir = os.path.dirname(tasks_yaml)

    with open(tasks_yaml, "r", encoding="utf-8") as f:
        tasks_doc = yaml.safe_load(f)

    # 加载 base 配置
    base_path = tasks_doc.get("base", "base.yaml")
    if not os.path.isabs(base_path):
        base_path = os.path.join(base_dir, base_path)
    with open(base_path, "r", encoding="utf-8") as f:
        base_cfg = yaml.safe_load(f)

    tasks = tasks_doc.get("tasks", [])
    print(f"=== 批量任务运行器 ===")
    print(f"  base: {base_path}")
    print(f"  任务数: {len(tasks)}")

    for task in tasks:
        name = task.get("name", "<unnamed>")
        if not task.get("enabled", False):
            print(f"\n[跳过] {name}（未启用）")
            continue
        if only_task and name != only_task:
            print(f"\n[跳过] {name}（仅运行 {only_task}）")
            continue

        print(f"\n{'='*60}")
        print(f"[运行] {name}")
        print(f"{'='*60}")

        # 合并 base + task（task 覆盖 base）
        task_cfg = _deep_merge(base_cfg, task)

        # 1. 自动生成 prob
        _handle_prob_auto_generate(task_cfg)

        # 2. 自动生成案例
        _handle_case_auto_generate(task_cfg)

        # 3. 构建运行时配置
        runtime = _build_runtime_config(task_cfg)

        # 4. 写入临时配置文件
        tmp_cfg = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        yaml.dump(runtime, tmp_cfg, allow_unicode=True, default_flow_style=False, sort_keys=False)
        tmp_cfg.close()
        print(f"  [config] 临时配置: {tmp_cfg.name}")

        # 5. 执行生成
        try:
            from main import run

            run(tmp_cfg.name, force=False)
            print(f"  [完成] {name}")
        except Exception as e:
            print(f"  [失败] {name}: {e}")
            raise
        finally:
            os.unlink(tmp_cfg.name)


def main():
    parser = argparse.ArgumentParser(description="批量任务运行器")
    parser.add_argument(
        "-t", "--tasks", type=str,
        default="demo/config/batch/milktea/tasks.yaml",
        help="任务列表 yaml 路径",
    )
    parser.add_argument(
        "--task", type=str, default=None,
        help="仅运行指定名称的任务",
    )
    args = parser.parse_args()
    run_tasks(args.tasks, only_task=args.task)


if __name__ == "__main__":
    main()
