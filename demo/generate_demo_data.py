#!/usr/bin/env python3
"""
奶茶店会员回访 Demo 虚拟数据生成脚本

生成完全虚构、固定种子、可复现的 demo 数据：
  - demo/data/话术模板.xlsx   (7 模块 sheet + 链接促销话术 sheet, 8 列)
  - demo/data/prob.xlsx       (7×7 整数百分比概率矩阵)
  - demo/data/cases/case_001~003.txt (奶茶店会员案例)
  - demo/demo_config.yaml     (demo 配置)

运行方式：
  python demo/generate_demo_data.py
"""

import os

import numpy as np
import pandas as pd
import yaml

# 固定种子，保证可复现
SEED = 42
np.random.seed(SEED)

# 目录路径（基于本文件位置，不依赖 cwd）
DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DEMO_DIR, "data")
CASES_DIR = os.path.join(DATA_DIR, "cases")

# 8 列结构（与 core/data/data_loader.py keep_cols 一致）
COLUMNS = [
    "uid",
    "parent(继承)",
    "repeat(次数)",
    "conditions(条件)",
    "human(客户)",
    "assistant(专员)",
    "flexible_stop(可选不继承)",
    "是否再见",
]

# 模块名（与 prob 表行/列名一致）
MODULES = [
    "身份确认",
    "积分告知",
    "无意愿",
    "流失风险",
    "承诺到店",
    "已到店",
    "语音留言",
]


# ============================================================
# 1. 话术模板 Excel 数据
# ============================================================

def _sheet_data(rows):
    """将 list-of-dicts 转为 DataFrame，确保列顺序"""
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df


# --- 身份确认 (start, b_set) ---
SHEET_IDENTITY = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "喂你好 / 您好",
        "assistant(专员)": "您好请问是{客户姓名}{客户性别}吗 / 您好，请问是{客户姓氏}吗",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 2, "parent(继承)": 1, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "是的我是 / 对，是我",
        "assistant(专员)": "{客户姓名}您好，我是{门店名称}{专员工号}号专员，今天致电是想跟您做个会员回访 / 您好{客户姓名}{客户性别}，我是{门店名称}的客服，工号{专员工号}，今天来跟您做个会员回访",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 3, "parent(继承)": 2, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "哦好的你说 / 嗯，什么情况",
        "assistant(专员)": "是这样的，您目前是{门店名称}的{会员等级}会员，积分余额{积分余额}分，想确认下您近期是否有到店消费的打算 / 查到您在我们{门店名称}的等级是{会员等级}，积分余额{积分余额}分",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
]

# --- 积分告知 (b_set) ---
SHEET_POINTS = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1/2",
        "conditions(条件)": "",
        "human(客户)": "积分还有多少 / 我的积分什么情况",
        "assistant(专员)": "您目前积分余额{积分余额}分，按{会员等级}会员权益可兑换饮品或抵扣消费 / 积分余额{积分余额}分，{会员等级}会员可享受积分兑换和消费抵扣",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 2, "parent(继承)": 1, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "那能怎么用 / 积分能干嘛",
        "assistant(专员)": "积分可兑换{门店名称}指定饮品，消费时每100积分抵扣{应还金额}元 / 积分能兑换饮品，消费时每100积分可抵{应还金额}元",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 3, "parent(继承)": 2, "repeat(次数)": "2",
        "conditions(条件)": "",
        "human(客户)": "哦这样啊 / 我考虑一下",
        "assistant(专员)": "温馨提示，您的积分在{到期日期}前有效，到期未使用将清零，建议近期到店使用 / 积分将在{到期日期}到期，建议到期前到店使用哦",
        "flexible_stop(可选不继承)": 1, "是否再见": 0,
    },
]

# --- 无意愿 (b_set, insert_nodes) ---
SHEET_NO_INTEREST = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "我不怎么去你们店了 / 算了不用了",
        "assistant(专员)": "理解您{客户姓名}，不过您的{积分余额}分积分如果不用就浪费了，要不要考虑近期来一趟 / {客户姓名}{客户性别}，{积分余额}分积分来之不易，不用可惜了",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 2, "parent(继承)": 1, "repeat(次数)": "1/2",
        "conditions(条件)": "",
        "human(客户)": "最近没时间 / 改天再说吧",
        "assistant(专员)": "没关系，您随时可以来{门店名称}，积分兑换活动一直都有 / 没关系的{客户姓名}，{门店名称}随时欢迎您，积分活动长期有效",
        "flexible_stop(可选不继承)": 1, "是否再见": 0,
    },
    {
        "uid": 3, "parent(继承)": 2, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "好吧那我改天去 / 行吧我有空看看",
        "assistant(专员)": "太好了{客户姓名}，期待您光临，到店出示{小程序名称}会员码即可 / 好的，到店后出示{小程序名称}的会员码就行，会有专属优惠",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
]

# --- 流失风险 (a_set, insert_nodes) ---
SHEET_CHURN_RISK = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "你们的奶茶越来越难喝了 / 之前体验不好不想去了",
        "assistant(专员)": "非常抱歉给您带来不好的体验{客户姓名}，{门店名称}一直在改进产品，最近推出了好几款新品 / {客户姓名}{客户性别}，听到您这样说很抱歉，我们已经改进了配方，近期有很多新品",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 2, "parent(继承)": 1, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "新品有什么 / 有什么推荐的",
        "assistant(专员)": "新推出了芝芝莓莓和杨枝甘露，{会员等级}会员首杯半价优惠 / 推荐试试芝芝莓莓和杨枝甘露，{会员等级}会员首杯半价哦",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 3, "parent(继承)": 2, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "半价还行 / 那可以试试",
        "assistant(专员)": "好的{客户姓名}，半价优惠到{到期日期}截止，到店跟店员说是{会员等级}会员即可 / 太好了，半价活动到{到期日期}，到店出示会员码就能享受",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
]

# --- 承诺到店 (b_set, 再见=1) ---
SHEET_PROMISE_VISIT = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "行那我这两天去一趟 / 好的我去看看",
        "assistant(专员)": "好的{客户姓名}，期待您到店，有问题可打{门店电话}联系我们 / 太好了{客户姓名}，期待您光临{门店名称}，有问题随时拨打{门店电话}",
        "flexible_stop(可选不继承)": 0, "是否再见": 1,
    },
    {
        "uid": 2, "parent(继承)": 1, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "好的谢谢 / 行，再见",
        "assistant(专员)": "感谢您的接听{客户姓名}，祝您生活愉快，再见 / 谢谢您{客户姓氏}，再见，期待您的光临",
        "flexible_stop(可选不继承)": 0, "是否再见": 1,
    },
]

# --- 已到店 (terminal) ---
SHEET_ARRIVED = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "我已经到店了 / 我刚去你们店了",
        "assistant(专员)": "感谢您的光临{客户姓名}，积分兑换已为您办理，欢迎下次再来 / 太好了{客户姓名}，已为您核销积分，期待您下次光临{门店名称}",
        "flexible_stop(可选不继承)": 0, "是否再见": 1,
    },
]

# --- 语音留言 (self_loop) ---
SHEET_VOICEMAIL = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "",
        "assistant(专员)": "您好{客户姓名}，这里是{门店名称}客服，关于您的{积分余额}分积分即将到期，请有空时回电{门店电话}，感谢 / 您好，{门店名称}客服温馨提示，您的{积分余额}分积分即将到期，详情请回电{门店电话}",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
]

# --- 链接促销话术 (pressure sheet，替代催收施压) ---
SHEET_PROMOTION = [
    {
        "uid": 1, "parent(继承)": None, "repeat(次数)": "1",
        "conditions(条件)": "",
        "human(客户)": "",
        "assistant(专员)": "顺便跟您说下，{门店名称}本周有会员日双倍积分活动，消费满{应还金额}元额外赠送{随机金额}积分 / 另外提醒您{客户姓名}，本周会员日消费有双倍积分，满{应还金额}元还送{随机金额}积分",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 2, "parent(继承)": 1, "repeat(次数)": "2",
        "conditions(条件)": "",
        "human(客户)": "是吗还有什么活动",
        "assistant(专员)": "还有储值充{应还金额}送{随机金额}的活动，{会员等级}会员额外加赠一杯饮品 / 储值充{应还金额}送{随机金额}，{会员等级}会员还额外赠送一杯饮品哦",
        "flexible_stop(可选不继承)": 0, "是否再见": 0,
    },
    {
        "uid": 3, "parent(继承)": 2, "repeat(次数)": "3",
        "conditions(条件)": "",
        "human(客户)": "好的我看看 / 行有空我去",
        "assistant(专员)": "好的{客户姓名}，活动详情可到{小程序名称}查看，或到店咨询店员 / 活动详情可到{小程序名称}查看，到店时直接问店员也行",
        "flexible_stop(可选不继承)": 1, "是否再见": 0,
    },
]

MODULE_SHEETS = {
    "身份确认": SHEET_IDENTITY,
    "积分告知": SHEET_POINTS,
    "无意愿": SHEET_NO_INTEREST,
    "流失风险": SHEET_CHURN_RISK,
    "承诺到店": SHEET_PROMISE_VISIT,
    "已到店": SHEET_ARRIVED,
    "语音留言": SHEET_VOICEMAIL,
}


def generate_excel():
    """生成话术模板 Excel"""
    path = os.path.join(DATA_DIR, "话术模板.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, rows in MODULE_SHEETS.items():
            _sheet_data(rows).to_excel(writer, sheet_name=name, index=False)
        # 促销话术 sheet
        _sheet_data(SHEET_PROMOTION).to_excel(
            writer, sheet_name="链接促销话术", index=False
        )
    print(f"  生成: {path}")
    return path


# ============================================================
# 2. 概率矩阵 Excel
# ============================================================

def generate_prob_matrix():
    """生成 7×7 整数百分比概率矩阵"""
    # 行=from，列=to，每行和=100
    # terminal(已到店) 和 self_loop(语音留言) 行全 0（校验跳过）
    rows = [
        # 身份确认→  积分  无意  流失  承诺  已到  语音
        [0,  70, 15,  5,  0,  0, 10],  # 身份确认
        [0,   0, 25, 10, 40, 20,  5],  # 积分告知
        [0,  30,  0, 20, 30,  5, 15],  # 无意愿
        [0,  20,  0,  0, 50, 15, 15],  # 流失风险
        [0,  10,  0,  0,  0, 80, 10],  # 承诺到店
        [0,   0,  0,  0,  0,  0,  0],  # 已到店
        [0,   0,  0,  0,  0,  0,  0],  # 语音留言
    ]
    df = pd.DataFrame(rows, index=MODULES, columns=MODULES)

    path = os.path.join(DATA_DIR, "prob.xlsx")
    df.to_excel(path, sheet_name="prob", index=True)
    print(f"  生成: {path}")
    return path


# ============================================================
# 3. 案例 .txt 文件
# ============================================================

CASES = [
    {
        "filename": "case_001.txt",
        "intro": "你是{门店名称}的会员回访专员，工号{专员工号}。今天致电VIP会员{客户姓名}{客户性别}，告知其积分余额{积分余额}分即将在{到期日期}到期，引导其到店消费使用积分。",
        "fields": {
            "门店名称": "茗香茶饮",
            "门店电话": "400-888-9999",
            "会员等级": "VIP",
            "积分余额": "1250",
            "应还金额": "35元",
            "到期日期": "2026年12月31日",
            "客户姓名": "李雪",
            "客户性别": "女士",
            "客户姓氏": "李女士",
            "专员工号": "A102",
            "小程序名称": "茗香小程序",
            "今天日期": "2026年10月10日",
            "当前时间": "上午10点",
            "查账时间": "2026年10月10日 09:30",
        },
    },
    {
        "filename": "case_002.txt",
        "intro": "你是{门店名称}的会员回访专员，工号{专员工号}。今天致电普通会员{客户姓名}{客户性别}，其积分余额{积分余额}分，引导其到店兑换饮品或参加会员日活动。",
        "fields": {
            "门店名称": "茗香茶饮",
            "门店电话": "400-888-9999",
            "会员等级": "普通",
            "积分余额": "380",
            "应还金额": "20元",
            "到期日期": "2026年11月15日",
            "客户姓名": "王强",
            "客户性别": "先生",
            "客户姓氏": "王先生",
            "专员工号": "A205",
            "小程序名称": "茗香小程序",
            "今天日期": "2026年10月10日",
            "当前时间": "下午2点",
            "查账时间": "2026年10月10日 14:00",
        },
    },
    {
        "filename": "case_003.txt",
        "intro": "你是{门店名称}的会员回访专员，工号{专员工号}。今天致电VIP会员{客户姓名}{客户性别}，其积分余额{积分余额}分，近期消费金额{应还金额}，推荐新品半价活动并引导到店。",
        "fields": {
            "门店名称": "茗香茶饮",
            "门店电话": "400-888-9999",
            "会员等级": "VIP",
            "积分余额": "2100",
            "应还金额": "48元",
            "到期日期": "2027年1月20日",
            "客户姓名": "张敏",
            "客户性别": "女士",
            "客户姓氏": "张女士",
            "专员工号": "A103",
            "小程序名称": "茗香小程序",
            "今天日期": "2026年10月10日",
            "当前时间": "下午3点半",
            "查账时间": "2026年10月10日 15:15",
        },
    },
]


def generate_cases():
    """生成案例 .txt 文件"""
    for case in CASES:
        path = os.path.join(CASES_DIR, case["filename"])
        lines = [case["intro"], ""]
        for k, v in case["fields"].items():
            lines.append(f"- {k}：{v}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  生成: {path}")


# ============================================================
# 4. demo_config.yaml
# ============================================================

DEMO_CONFIG = {
    "company": "milktea_demo",
    "task_name": "milktea_member_callback",
    "start_module": "身份确认",
    "output_dir": "output",
    "paths_cache_dir": "paths_demo",
    "paths_cache": "output/paths_demo/all_paths_{num_paths}_{seed}.json",

    "num_paths": 5,
    "num_dialogues": 5,
    "num_paths_to_generate": 5,
    "random_seed": 42,
    "checkpoint_interval": 100,

    "prob_path": "demo/data/prob.xlsx",
    "excel_path": "demo/data/话术模板.xlsx",

    "case_loader": {
        "type": "default",
    },
    "cases_dir": "demo/data/cases",

    "a_set": ["流失风险"],
    "b_set": ["身份确认", "积分告知", "无意愿", "承诺到店"],
    "terminal_modules": ["已到店"],
    "self_loop_modules": {"语音留言": 0.05},
    "insert_nodes": ["无意愿", "流失风险"],

    "pressure_sheet_name": "链接促销话术",

    "pressure_prob": 0.3,
    "pressure_dynamic_enabled": True,
    "pressure_calc_type": "exponential",
    "pressure_start_prob": 0.05,
    "pressure_end_prob": 0.6,
    "pressure_curve_exponent": 2.0,
    "pressure_max_total": 3,
    "pressure_strategy": {"type": "normalized"},
    "module_pressure_weights": {
        "无意愿": 1.2,
        "流失风险": 1.0,
    },

    "flexible_stop_prob": 0.3,
    "goodbye_termination_prob": 0.7,
    "goodbye_dynamic_enabled": True,
    "goodbye_calc_type": "exponential",
    "goodbye_start_prob": 0.05,
    "goodbye_end_prob": 0.8,
    "goodbye_exponent": 3.0,
    "goodbye_min_idx": 2,

    "time_generator": {"type": "simple_natural"},

    "trace_enabled": False,
    "logging": {
        "level": "INFO",
        "file_prefix": "dialogue_builder",
        "console": True,
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    },

    "dedup": {"enabled": False},
    "analysis": {"enabled": False},
    "multiprocessing": {"num_processes": 1},
}


def generate_config():
    """生成 demo_config.yaml"""
    path = os.path.join(DEMO_DIR, "demo_config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(DEMO_CONFIG, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  生成: {path}")


# ============================================================
# 主函数
# ============================================================

def main():
    print("=== 生成奶茶店会员回访 Demo 虚拟数据 ===")
    print(f"  种子: {SEED}")
    print(f"  输出目录: {DATA_DIR}")
    print()

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CASES_DIR, exist_ok=True)

    print("[1/4] 生成话术模板 Excel...")
    generate_excel()

    print("[2/4] 生成概率矩阵 Excel...")
    generate_prob_matrix()

    print("[3/4] 生成案例文件...")
    generate_cases()

    print("[4/4] 生成配置文件...")
    generate_config()

    print()
    print("=== 全部生成完成 ===")
    print("验证方法:")
    print("  python -c \"import sys;sys.path.insert(0,'scripts_general');from core.data.data_loader import load_prob_matrix;print(load_prob_matrix('demo/data/prob.xlsx'))\"")


if __name__ == "__main__":
    main()
