"""
概率矩阵生成器：从 categories.yaml 配置生成 prob.xlsx。

根据模块分类（A/B/C）、手动候选集（manual）、固定概率（fixed_prob）、
业务偏好倍数（boost / self_loop_boost）计算每个模块的出边概率分布，
输出与 core/data/data_loader.py 兼容的 15×15 整数百分比矩阵。

用法：
    from core.data.prob_generator import generate_prob_from_categories
    generate_prob_from_categories("demo/config/categories.yaml", "demo/data/prob.xlsx")
"""

import os
from typing import Dict, List

import pandas as pd
import yaml


def _resolve_self_loop_boost(module: str, category: str, cfg: dict) -> float:
    """获取某模块的自循环权重倍数"""
    overrides = cfg.get("self_loop_boost_override", {})
    if module in overrides:
        return float(overrides[module])
    slb = cfg.get("self_loop_boost", {})
    if category in slb:
        return float(slb[category])
    return float(slb.get("default", 1.0))


def _module_category(module: str, a_set: set, b_set: set) -> str:
    """判断模块属于 A / B / default"""
    if module in a_set:
        return "A"
    if module in b_set:
        return "B"
    return "default"


def generate_prob_from_categories(categories_path: str, output_path: str) -> pd.DataFrame:
    """
    从 categories.yaml 生成概率矩阵并写入 prob.xlsx。

    :param categories_path: categories.yaml 路径
    :param output_path: 输出 prob.xlsx 路径
    :return: 生成的 DataFrame
    """
    with open(categories_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    a_set = set(cfg.get("A", []))
    b_set = set(cfg.get("B", []))
    c_set = set(cfg.get("C", []))
    manual = cfg.get("manual", {})
    fixed_prob = cfg.get("fixed_prob", {})
    boost = cfg.get("boost", {})

    # 模块全集 = A + B + C + manual 中出现的所有模块
    all_modules: List[str] = []
    seen = set()
    for m in list(a_set) + list(b_set) + list(c_set):
        if m not in seen:
            all_modules.append(m)
            seen.add(m)
    for m in manual:
        if m not in seen:
            all_modules.append(m)
            seen.add(m)

    rows: Dict[str, List[int]] = {}
    for module in all_modules:
        # 1. 候选出边：manual 优先，否则默认 A+B+C
        if module in manual:
            candidates = list(manual[module])
        else:
            candidates = [m for m in all_modules if m != module]

        # 2. 计算每个候选的基础权重
        cat = _module_category(module, a_set, b_set)
        weights: Dict[str, float] = {}
        for cand in candidates:
            w = 1.0
            if cand == module:
                w *= _resolve_self_loop_boost(module, cat, cfg)
            if cand in boost:
                w *= float(boost[cand])
            weights[cand] = w

        # 3. 应用固定概率
        fixed = fixed_prob.get(module, {})
        fixed_sum = sum(fixed.values())
        if fixed_sum > 100:
            raise ValueError(f"模块 {module} 的 fixed_prob 之和 {fixed_sum} > 100")

        # 4. 非固定候选按权重分配剩余概率
        non_fixed = {c: w for c, w in weights.items() if c not in fixed}
        non_fixed_sum = sum(non_fixed.values())
        probs: Dict[str, float] = {}
        remaining = 100.0 - fixed_sum

        for c, pct in fixed.items():
            probs[c] = float(pct)

        if non_fixed_sum > 0 and remaining > 0:
            for c, w in non_fixed.items():
                probs[c] = w / non_fixed_sum * remaining
        elif remaining > 0 and not non_fixed:
            # 没有非固定候选，把剩余概率均摊到固定项（不应发生）
            for c in fixed:
                probs[c] += remaining / len(fixed)

        # 5. 四舍五入为整数，修正总和为 100
        int_probs = {c: int(round(p)) for c, p in probs.items()}
        diff = 100 - sum(int_probs.values())
        if diff != 0 and int_probs:
            # 把差值加到权重最大的候选上
            max_cand = max(int_probs, key=lambda c: probs[c])
            int_probs[max_cand] += diff

        rows[module] = [int_probs.get(m, 0) for m in all_modules]

    df = pd.DataFrame(rows.values(), index=all_modules, columns=all_modules)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    df.to_excel(output_path, sheet_name="prob", index=True)
    return df


if __name__ == "__main__":
    import sys

    cat = sys.argv[1] if len(sys.argv) > 1 else "demo/config/categories.yaml"
    out = sys.argv[2] if len(sys.argv) > 2 else "demo/data/prob.xlsx"
    df = generate_prob_from_categories(cat, out)
    print(f"已生成概率矩阵: {out}（{df.shape[0]}×{df.shape[1]}）")
    print(df)
