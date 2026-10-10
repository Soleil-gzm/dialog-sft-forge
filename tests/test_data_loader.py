"""数据加载测试：案例解析 + demo 数据冒烟。"""

from core.data.data_loader import (load_cases, load_prob_matrix, load_sheets,
                                   parse_case_info)
from core.utils.random_service import RandomService

PROB_PATH = "demo/data/prob.xlsx"
EXCEL_PATH = "demo/data/话术模板.xlsx"
CASES_DIR = "demo/data/cases"


class TestParseCaseInfo:
    def test_generic_fields(self):
        case = parse_case_info(f"{CASES_DIR}/case_001.txt")
        assert case["门店名称"] == "茗香茶饮"
        assert case["会员等级"] == "VIP"

    def test_numeric_suffix(self):
        """纯数字值自动附加 int 型 _数值，含单位值附加 float 型 _数值"""
        case = parse_case_info(f"{CASES_DIR}/case_001.txt")
        assert case["积分余额_数值"] == 1250
        assert isinstance(case["积分余额_数值"], int)
        assert case["消费金额_数值"] == 35.0

    def test_generated_random_fields(self):
        rng = RandomService(42)
        case = parse_case_info(f"{CASES_DIR}/case_001.txt", rng=rng)
        assert case["随机金额"].isdigit()
        assert case["随机数字"].isdigit()
        assert case["随机时间"]


class TestDemoDataSmoke:
    def test_load_prob_matrix(self):
        prob_df, modules = load_prob_matrix(PROB_PATH)
        assert len(modules) == 7
        assert prob_df.values.min() >= 0
        # 非终止/非自循环行概率和归一为 1
        for m in ["身份确认", "积分告知", "无意愿", "流失风险", "承诺到店"]:
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
        assert len(cases) == 3
        assert len(prompts) == 3
        assert all("门店名称" in c for c in cases)
