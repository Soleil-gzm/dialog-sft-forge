"""评测运行器端到端测试：FakeLLM 注入，覆盖全对 / 失败 / 抽样分支。"""

import os

from agent.core.config import load_agent_config
from agent.eval.case_schema import load_testset
from agent.eval.fake_llm import FakeLLM, tool_call
from agent.eval.runner import run_eval

CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agent", "config", "agent_config.yaml"
)
TESTSET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agent", "eval", "testset.yaml"
)


def test_mock_perfect_all_pass():
    config = load_agent_config(CONFIG)
    testset = load_testset(TESTSET)

    def factory(case):
        return FakeLLM(FakeLLM.perfect_script(case.expected_tools, case.member_id, case.requires_knowledge))

    data = run_eval(config, testset, mock=True)
    assert data["summary"]["num_cases"] == len(testset)
    assert data["summary"]["num_passed"] == len(testset)
    assert data["summary"]["pass_rate"] == 1.0
    assert all(r["passed"] for r in data["results"])


def test_broken_script_all_fail():
    config = load_agent_config(CONFIG)
    testset = load_testset(TESTSET)

    # 坏脚本：只调 query_member_profile 就答复，缺 log_visit_result 与其余必调工具
    def factory(case):
        return FakeLLM([
            {"tool_calls": [tool_call("query_member_profile", {"member_id": case.member_id})]},
            {"content": "好的，已完成。"},
        ])

    data = run_eval(config, testset, llm_factory=factory)
    assert data["summary"]["num_passed"] == 0
    # 失败样本应保留 trace
    assert all("trace" in r for r in data["results"])


def test_limit_sampling():
    config = load_agent_config(CONFIG)
    testset = load_testset(TESTSET)
    data = run_eval(config, testset, limit=3, seed=0, mock=True)
    assert data["summary"]["num_cases"] == 3
    # 同 seed 抽样结果稳定
    data2 = run_eval(config, testset, limit=3, seed=0, mock=True)
    assert [r["case_id"] for r in data["results"]] == [r["case_id"] for r in data2["results"]]
