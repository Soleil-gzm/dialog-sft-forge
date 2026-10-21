"""M5 backflow 模块单测：转换纯函数 / 注入幂等 / 容器一致。"""

import json
import os
import tempfile

import pytest

from agent.eval.backflow.bridge import (
    coupon_for_level,
    map_fields,
    member_id_for_case,
    synthesize_purchase_history,
)
from agent.eval.backflow.convert import (
    derive_acceptance,
    derive_expected_tools,
    messages_to_task,
    to_eval_case,
)
from agent.eval.backflow.seed import ensure_member
from agent.eval.case_schema import EvalCase

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_DIR = os.path.join(_PROJ, "demo", "data", "case", "cases")
PROMPTS_DIR = os.path.join(_PROJ, "demo", "data", "case", "prompts")


def _read_case_file(name: str) -> dict:
    with open(os.path.join(CASES_DIR, name), "r", encoding="utf-8") as f:
        return _parse_case_text(f.read())


def _parse_case_text(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        for sep in ("：", ":"):
            if sep in line[2:]:
                k, v = line[2:].split(sep, 1)
                if k.strip():
                    out[k.strip()] = v.strip()
                break
    return out


def _read_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture()
def case_0001():
    return _read_case_file("case_0001.txt")


@pytest.fixture()
def prompt_0001():
    return _read_prompt("case_0001.txt")


# ---------------- bridge ----------------
def test_member_id_format():
    assert member_id_for_case(1) == "BF0001"
    assert member_id_for_case(42) == "BF0042"


def test_map_fields_matches_case():
    case = {
        "客户姓名": "赵娟", "客户性别": "女士", "会员等级": "银卡",
        "积分余额": "757", "到期日期": "2027年5月2日", "消费金额": "49元",
    }
    m = map_fields(case)
    assert m["name"] == "赵娟"
    assert m["gender"] == "女士"
    assert m["level"] == "银卡"
    assert m["points"] == 757
    assert m["points_expire"] == "2027-05-02"
    assert m["last_purchase_amount"] == 49


def test_synthesize_purchase_history_nonempty():
    h = synthesize_purchase_history({"会员等级": "银卡"}, "BF0001")
    assert h and h[0]["product"] and h[0]["amount"] > 0


def test_coupon_for_level_buckets():
    assert len(coupon_for_level("VIP")) == 2
    assert coupon_for_level("普通")[0]["threshold"] == 20


# ---------------- convert ----------------
def test_derive_expected_tools_points_and_coupon(case_0001, prompt_0001):
    tools, rk = derive_expected_tools(case_0001, prompt_0001, [])
    assert "query_member_profile" in tools
    assert "calc_best_coupon" in tools
    assert "log_visit_result" in tools
    assert isinstance(rk, bool)


def test_derive_expected_tools_knowledge_for_policy_q():
    case = {"积分余额": "90", "会员等级": "普通"}
    prompt = "告知会员积分怎么抵扣现金"
    tools, rk = derive_expected_tools(case, prompt, [])
    assert rk is True


def test_messages_to_task_prefers_case_fields(case_0001):
    task = messages_to_task([], case_0001)
    assert "赵娟" in task and "757" in task


def test_to_eval_case_roundtrip(case_0001, prompt_0001):
    ec = to_eval_case("BF0001_0001", "BF0001", case_0001, prompt_0001, [])
    assert isinstance(ec, EvalCase)
    assert ec.member_id == "BF0001"
    assert ec.expected_tools
    assert ec.id == "BF0001_0001"


def test_derive_acceptance_maps():
    case = {"优惠券": "满20减5券", "积分余额": "757"}
    acc = derive_acceptance(case, "告知积分并推荐优惠", [])
    assert any("优惠" in a for a in acc)


# ---------------- seed ----------------
def test_seed_ensure_member_idempotent_and_readable():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "mock.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "members": {}, "coupons": {}, "purchase_history": {}, "inventory": {},
            }, f)

        case = {
            "客户姓名": "赵娟", "客户性别": "女士", "会员等级": "银卡",
            "积分余额": "757", "到期日期": "2027年5月2日", "消费金额": "49元",
        }
        # 依赖 agent.tools.business_tools.load_mock_data 缓存
        from agent.tools.business_tools import load_mock_data, _DATA_CACHE
        first = ensure_member(p, "BF0001", case)
        second = ensure_member(p, "BF0001", case)  # 幂等
        assert second is first

        data = load_mock_data(p)
        assert data["members"]["BF0001"]["points"] == 757
        assert "银卡" in data["coupons"]  # 补了券桶
        assert data["purchase_history"]["BF0001"]

        # 磁盘内容不被改动（注入只在内存态）
        on_disk = json.load(open(p, encoding="utf-8"))
        assert on_disk["members"] == {}
        _DATA_CACHE.pop(p, None)