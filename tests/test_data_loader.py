"""数据加载测试：案例解析 + demo 数据冒烟。"""

import os

from core.data.data_loader import (load_cases, load_prob_matrix, load_sheets,
                                   parse_case_info)
from core.utils.random_service import RandomService

PROB_PATH = "demo/data/prob.xlsx"
EXCEL_PATH = "demo/data/话术模板.xlsx"
CASES_DIR = "demo/data/cases"
PROMPTS_DIR = "demo/data/prompts"

NUM_MODULES = 15
NUM_CASES = 500
# 非终端、非自循环节点：概率行归一为 1
NORMALIZED_ROWS = [
    "身份确认", "身份核实", "积分告知", "权益介绍", "活动推荐",
    "无意愿", "犹豫跟进", "承诺到店", "预约到店", "流失风险", "投诉处理",
]


class TestParseCaseInfo:
    def test_generic_fields(self):
        case = parse_case_info(f"{CASES_DIR}/case_0001.txt")
        assert case["门店名称"].startswith("茗香茶饮")
        assert case["小程序名称"] == "茗香小程序"

    def test_numeric_suffix(self):
        """纯数字值自动附加 int 型 _数值，含单位值附加 float 型 _数值"""
        case = parse_case_info(f"{CASES_DIR}/case_0001.txt")
        assert isinstance(case["积分余额_数值"], int)
        assert isinstance(case["消费金额_数值"], float)

    def test_generated_random_fields(self):
        rng = RandomService(42)
        case = parse_case_info(f"{CASES_DIR}/case_0001.txt", rng=rng)
        assert case["随机金额"].isdigit()
        assert case["随机数字"].isdigit()
        assert case["随机时间"]


class TestDemoDataSmoke:
    def test_load_prob_matrix(self):
        prob_df, modules = load_prob_matrix(PROB_PATH)
        assert len(modules) == NUM_MODULES
        assert prob_df.values.min() >= 0
        for m in NORMALIZED_ROWS:
            assert abs(prob_df.loc[m].sum() - 1.0) < 1e-9

    def test_load_sheets(self):
        _, modules = load_prob_matrix(PROB_PATH)
        df_dict = load_sheets(EXCEL_PATH, modules)
        assert set(df_dict.keys()) == set(modules)
        for df in df_dict.values():
            assert not df.empty

    def test_load_cases(self):
        rng = RandomService(42)
        cases, prompts = load_cases(CASES_DIR, rng=rng)
        assert len(cases) == NUM_CASES
        assert all("门店名称" in c for c in cases)
        # prompts 由 split 加载器单独加载，与案例一一对应
        prompt_files = sorted(
            f for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt")
        )
        assert len(prompt_files) == NUM_CASES
        assert all(
            open(os.path.join(PROMPTS_DIR, f), encoding="utf-8").read().strip()
            for f in prompt_files
        )
