"""
案例生成器：根据 prompt 模板（system.txt / replace.txt）生成案例与配对 prompt。

当前支持 generator_type="milktea"（奶茶店会员回访场景）。
生成逻辑：确定性随机填充占位符，输出：
  - replace_dir/*.txt  : `- 字段：值` 逐行格式的案例文件
  - system_dir/*.txt   : 由 system.txt 模板填充占位符后的 system prompt

用法：
    from core.data.case_generator import generate_cases
    generate_cases(
        generator_type="milktea",
        prompt_dir="demo/prompt",
        replace_dir="demo/data/cases",
        system_dir="demo/data/prompts",
        num_cases=2000,
        seed=11,
    )
"""

import os
import random
import re
from typing import Dict, List


# ============================================================
# 奶茶店场景数据池
# ============================================================
_SURNAMES = list("李王张刘陈杨黄赵周吴徐孙马朱胡郭何高林罗郑梁谢宋唐")
_GIVEN_FEMALE = ["雪", "敏", "静", "婷", "慧", "琳", "娜", "芳", "娟", "霞",
                 "秀英", "倩", "妍", "洁", "雯", "璐", "瑶", "蕾", "薇", "萍",
                 "雨桐", "若曦", "佳琪", "诗涵", "欣怡"]
_GIVEN_MALE = ["强", "伟", "军", "勇", "磊", "涛", "鹏", "超", "刚", "明",
               "辉", "亮", "杰", "鑫", "浩", "宇", "轩", "博", "文", "龙",
               "子轩", "浩然", "俊杰", "天佑", "致远"]
_BRANCHES = ["万达店", "万象城店", "大学城店", "中央广场店", "滨江店",
             "高新园店", "火车站店", "老城区店", "银泰店", "紫荆店"]
_PHONES = ["400-888-9999", "400-666-8888", "400-999-1111", "400-123-4567", "400-555-7777"]
_LEVELS = ["普通", "银卡", "金卡", "VIP"]
_LEVEL_WEIGHTS = [40, 25, 20, 15]
_POINTS_RANGE = {
    "普通": (0, 800),
    "银卡": (300, 2000),
    "金卡": (1000, 4000),
    "VIP": (2000, 8000),
}
_COUPONS = ["满20减5券", "新品半价券", "买一送一券", "免配送费券", "满30减10券", "升杯券"]
_TIMES = ["上午10点", "上午11点", "中午12点", "下午2点", "下午3点",
          "下午4点", "下午5点", "傍晚6点"]
_TODAY = "2026年10月11日"


def _expire_date(rng: random.Random) -> str:
    """生成 2026-11 ~ 2027-08 的到期日期"""
    month = rng.randint(11, 20)
    year = 2026 if month <= 12 else 2027
    month = month if month <= 12 else month - 12
    day = rng.randint(1, 28)
    return f"{year}年{month}月{day}日"


def _generate_milktea_records(num_cases: int, seed: int) -> List[Dict[str, str]]:
    """生成奶茶店会员回访案例字段记录（确定性随机）"""
    rng = random.Random(seed)
    records = []
    for _ in range(num_cases):
        level = rng.choices(_LEVELS, weights=_LEVEL_WEIGHTS, k=1)[0]
        is_female = rng.random() < 0.5
        given = rng.choice(_GIVEN_FEMALE if is_female else _GIVEN_MALE)
        surname = rng.choice(_SURNAMES)
        gender = "女士" if is_female else "先生"
        lo, hi = _POINTS_RANGE[level]
        points = rng.randint(lo, hi)
        coupon = rng.choice(_COUPONS) if rng.random() < 0.6 else ""
        branch = rng.choice(_BRANCHES)
        fields = {
            "门店名称": f"茗香茶饮（{branch}）",
            "门店电话": rng.choice(_PHONES),
            "会员等级": level,
            "积分余额": str(points),
            "消费金额": f"{rng.randint(12, 68)}元",
            "优惠券": coupon,
            "到期日期": _expire_date(rng),
            "客户姓名": surname + given,
            "客户性别": gender,
            "客户姓氏": surname + gender,
            "专员工号": f"A{rng.randint(101, 299)}",
            "小程序名称": "茗香小程序",
            "今天日期": _TODAY,
            "当前时间": rng.choice(_TIMES),
        }
        records.append(fields)
    return records


_GENERATORS = {
    "milktea": _generate_milktea_records,
}


def _clean_txt_dir(directory: str) -> None:
    """清空目录下的 .txt 文件"""
    os.makedirs(directory, exist_ok=True)
    for name in os.listdir(directory):
        if name.endswith(".txt"):
            os.remove(os.path.join(directory, name))


def _extract_placeholders(template: str) -> List[str]:
    """提取模板中所有 {占位符}"""
    return re.findall(r"\{(\w+)\}", template)


def generate_cases(
    generator_type: str,
    prompt_dir: str,
    replace_dir: str,
    system_dir: str,
    num_cases: int,
    seed: int = 42,
) -> int:
    """
    生成案例文件与配对 prompt 文件。

    :param generator_type: 生成器类型，如 "milktea"
    :param prompt_dir: 存放 system.txt / replace.txt 模板的目录
    :param replace_dir: 案例文件输出目录
    :param system_dir: prompt 文件输出目录
    :param num_cases: 生成案例数量
    :param seed: 随机种子
    :return: 实际生成数量
    """
    if generator_type not in _GENERATORS:
        raise ValueError(f"不支持的 generator_type: {generator_type}，可选: {list(_GENERATORS)}")

    # 读取模板
    system_path = os.path.join(prompt_dir, "system.txt")
    replace_path = os.path.join(prompt_dir, "replace.txt")
    if not os.path.isfile(system_path):
        raise FileNotFoundError(f"system prompt 模板不存在: {system_path}")
    if not os.path.isfile(replace_path):
        raise FileNotFoundError(f"replace 模板不存在: {replace_path}")

    with open(system_path, "r", encoding="utf-8") as f:
        system_template = f.read()
    with open(replace_path, "r", encoding="utf-8") as f:
        replace_template = f.read()

    # 生成案例字段记录
    records = _GENERATORS[generator_type](num_cases, seed)

    _clean_txt_dir(replace_dir)
    _clean_txt_dir(system_dir)

    for idx, fields in enumerate(records, start=1):
        name = f"case_{idx:04d}"

        # 案例文件：按 replace.txt 模板填充
        case_text = replace_template.format(**fields)
        with open(os.path.join(replace_dir, name + ".txt"), "w", encoding="utf-8") as f:
            f.write(case_text)

        # prompt 文件：按 system.txt 模板填充
        prompt_text = system_template.format(**fields)
        with open(os.path.join(system_dir, name + ".txt"), "w", encoding="utf-8") as f:
            f.write(prompt_text)

    return len(records)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="生成案例与配对 prompt")
    parser.add_argument("--generator_type", default="milktea")
    parser.add_argument("--prompt_dir", default="demo/prompt")
    parser.add_argument("--replace_dir", default="demo/data/cases")
    parser.add_argument("--system_dir", default="demo/data/prompts")
    parser.add_argument("--num_cases", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    n = generate_cases(
        generator_type=args.generator_type,
        prompt_dir=args.prompt_dir,
        replace_dir=args.replace_dir,
        system_dir=args.system_dir,
        num_cases=args.num_cases,
        seed=args.seed,
    )
    print(f"已生成 {n} 个案例 → {args.replace_dir}")
    print(f"已生成 {n} 个配对 prompt → {args.system_dir}")
