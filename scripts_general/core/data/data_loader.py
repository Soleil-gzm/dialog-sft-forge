"""
数据加载模块。

load_sheets(excel_path, modules, keep_cols) → {module: DataFrame}
load_prob_matrix(prob_path) → (prob_df, modules)  # modules 的唯一来源
load_cases(cases_dir, rng, time_gen) → (cases_list, prompts_list)
"""

import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from core.utils.random_service import RandomService
from core.utils.time_generator import SimpleNaturalTimeGenerator, TimeGenerator

logger = logging.getLogger("DialogueBuilder")


def load_sheets(
    excel_path: str, modules: List[str], keep_cols: List[str] = None
) -> Dict[str, pd.DataFrame]:
    """
    按 prob 表定义的 modules 加载 Excel sheets，校验一致性。
    - prob 表要求的模块在 Excel 中缺失 → 报错
    - Excel 中多余的 sheet（非模块）→ 警告并忽略
    """
    xls = pd.ExcelFile(excel_path)
    excel_sheets = set(xls.sheet_names)

    # 校验：prob 表要求的模块必须存在于 Excel
    missing = [m for m in modules if m not in excel_sheets]
    if missing:
        xls.close()
        raise ValueError(f"Excel 缺少 prob 表要求的模块 sheet: {missing}")

    # 提示：Excel 中有 prob 表未定义的 sheet（忽略）
    known_extra = {"链接施压话术", "逻辑"}
    extra = excel_sheets - set(modules) - known_extra
    if extra:
        logger.warning(f"Excel 中有 prob 表未定义的 sheet（已忽略）: {extra}")

    if keep_cols is None:
        keep_cols = [
            "uid",
            "parent(继承)",
            "repeat(次数)",
            "conditions(条件)",
            "human(客户)",
            "assistant(专员)",
            "flexible_stop(可选不继承)",
            "是否再见",
        ]

    df_dict = {}
    for sheet in modules:
        df = pd.read_excel(excel_path, sheet_name=sheet)
        # 只保留需要的列，但不进行行过滤
        df_filtered = (
            df[keep_cols].copy()
            if all(c in df.columns for c in keep_cols)
            else df.loc[:, keep_cols].copy()
        )
        df_dict[sheet] = df_filtered
    xls.close()
    return df_dict


def load_prob_matrix(prob_path: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    加载概率矩阵，模块名从 index/columns 提取（唯一来源）。
    校验行列模块名一致后返回 (prob_df, modules)。
    """
    prob_df = pd.read_excel(prob_path, header=0, index_col=0)

    # 标准化模块名（strip 空白）
    modules = [str(m).strip() for m in prob_df.index]
    prob_df.index = modules
    prob_df.columns = [str(c).strip() for c in prob_df.columns]

    # 校验行列一致（以行模块名为基准）
    row_modules = set(prob_df.index)
    col_modules = set(prob_df.columns)
    missing_cols = row_modules - col_modules
    extra_cols = col_modules - row_modules

    if missing_cols:
        raise ValueError(
            f"prob 表列缺少行中定义的模块:\n"
            f"  缺失列模块: {sorted(missing_cols)}\n"
            f"  行模块名: {list(prob_df.index)}"
        )
    if extra_cols:
        logger.warning(f"prob 表有多余的列（行中未定义，已忽略）: {sorted(extra_cols)}")
        prob_df = prob_df.drop(columns=list(extra_cols))

    prob_df = prob_df / 100.0
    return prob_df, modules


def parse_case_info(
    txt_path: str,
    rng: Optional[RandomService] = None,
    time_gen: Optional[TimeGenerator] = None,
) -> Dict[str, Any]:
    """
    解析单个案例文件，返回字段字典。
    如果提供 rng，则使用它生成随机值；否则使用全局 random。
    如果提供 time_gen，则用它生成自然时间；否则使用 SimpleNaturalTimeGenerator。

    通用解析规则：
    - 每行格式为 "- 字段：值"（兼容中文/英文冒号），逐行解析进字段字典
    - 值为纯数字时自动附加 {字段}_数值（int），否则提取首个数字附加（float）
      供数值比较类条件（如 {积分余额}大于1000）使用
    """
    data = {}
    with open(txt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line.startswith("- "):
            continue
        rest = line[2:]
        sep = "：" if "：" in rest else (":" if ":" in rest else None)
        if sep is None:
            continue
        field = rest.split(sep, 1)[0].strip()
        if not field or field in data:
            continue
        value = rest.split(sep, 1)[1].strip()
        data[field] = value
        if re.fullmatch(r"\d+", value):
            data[field + "_数值"] = int(value)
        else:
            m = re.search(r"[\d.]+", value)
            if m:
                try:
                    data[field + "_数值"] = float(m.group())
                except ValueError:
                    pass

    # 生成随机字段
    if rng is not None:
        random_ratio = rng.uniform(0.3, 0.6)  # 30%~60%
        random_digits = rng.randint(1, 10)  # 1-10 整数
    else:
        random_ratio = random.uniform(0.3, 0.6)
        random_digits = random.randint(1, 10)

    # 随机金额：以"消费金额"数值为基数（若无该字段则为 0）
    base_amount = data.get("消费金额_数值", 0.0)
    data["随机金额"] = str(round(base_amount * random_ratio))
    data["随机数字"] = str(random_digits)

    # 生成自然口语化时间
    if rng is not None:
        if time_gen is None:
            time_gen = SimpleNaturalTimeGenerator()
        data["随机时间"] = time_gen.generate(rng)
    else:
        periods = ["上午", "下午"]
        period = random.choice(periods)
        hour = random.randint(9, 18)
        data["随机时间"] = f"今天{period}{hour}点"

    return data


def load_cases(
    cases_dir: str,
    rng: Optional[RandomService] = None,
    time_gen: Optional[TimeGenerator] = None,
) -> Tuple[List[Dict], List[str]]:
    """
    加载所有案例，返回 (cases列表, prompts列表)。
    如果提供 rng，则传递给 parse_case_info。
    如果提供 time_gen，则传递给 parse_case_info 用于生成自然时间。
    """
    case_files = sorted([f for f in os.listdir(cases_dir) if f.endswith(".txt")])
    cases = []
    prompts = []
    for fname in case_files:
        path = os.path.join(cases_dir, fname)
        cases.append(parse_case_info(path, rng=rng, time_gen=time_gen))
        with open(path, "r", encoding="utf-8") as f:
            prompts.append(f.read())
    return cases, prompts
