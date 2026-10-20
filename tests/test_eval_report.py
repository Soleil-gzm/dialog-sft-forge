"""评测报告生成测试：文件结构与内容校验。"""

import json
import os

import pytest

from agent.eval.case_schema import EvalCase
from agent.eval.report import write_report


def _case(**kw):
    defaults = dict(id="c1", member_id="M1001", task="t", expected_tools=["a", "log_visit_result"])
    defaults.update(kw)
    return EvalCase.from_dict(defaults)


def _result(case, answer="ok", passed=True, trace=None, steps=2):
    record = {
        "case_id": case.id,
        "member_id": case.member_id,
        "task": case.task,
        "answer": answer,
        "steps": steps,
        "truncated": False,
        "actions": case.expected_tools,
        "total_score": 0.9 if passed else 0.4,
        "passed": passed,
        "metrics": {
            "tool_coverage": 1.0, "task_completion": 1.0, "robustness": 1.0,
            "policy_citation": 1.0, "no_fabrication": 1.0, "efficiency": 0.8,
        },
    }
    if trace is not None:
        record["trace"] = trace
    return record


def test_write_report_creates_all_files(tmp_path):
    case_pass = _case(id="pass_case")
    case_fail = _case(id="fail_case")
    data = {
        "cases": [case_pass, case_fail],
        "results": [_result(case_pass, passed=True), _result(case_fail, passed=False, trace=[{"step": 1}])],
        "summary": {
            "num_cases": 2, "num_passed": 1, "pass_rate": 0.5,
            "avg_total_score": 0.65,
            "avg_metrics": {k: 0.9 for k in ["tool_coverage", "task_completion", "robustness", "policy_citation", "no_fabrication", "efficiency"]},
        },
        "use_llm_judge": False,
    }
    out = str(tmp_path)
    md = write_report(data, out)

    assert os.path.isfile(os.path.join(out, "report.md"))
    assert os.path.isfile(os.path.join(out, "report.json"))
    assert os.path.isfile(os.path.join(out, "cases.json"))
    assert os.path.isfile(os.path.join(out, "failures", "fail_case.json"))
    assert not os.path.exists(os.path.join(out, "failures", "pass_case.json"))

    # report.json 结构与内容
    with open(os.path.join(out, "report.json"), "r", encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["summary"]["num_passed"] == 1
    assert len(payload["results"]) == 2

    # 失败样本含 trace
    with open(os.path.join(out, "failures", "fail_case.json"), "r", encoding="utf-8") as f:
        fail = json.load(f)
    assert fail["passed"] is False
    assert "trace" in fail

    # markdown 关键内容
    with open(md, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Agent Eval 评测报告" in content
    assert "fail_case" in content


def test_write_report_empty_failures(tmp_path):
    case_pass = _case(id="only_pass")
    data = {
        "cases": [case_pass],
        "results": [_result(case_pass, passed=True)],
        "summary": {
            "num_cases": 1, "num_passed": 1, "pass_rate": 1.0,
            "avg_total_score": 0.9,
            "avg_metrics": {k: 1.0 for k in ["tool_coverage", "task_completion", "robustness", "policy_citation", "no_fabrication", "efficiency"]},
        },
        "use_llm_judge": False,
    }
    write_report(data, str(tmp_path))
    fail_dir = os.path.join(str(tmp_path), "failures")
    assert os.path.isdir(fail_dir)
    assert os.listdir(fail_dir) == []


def test_write_report_all_failed(tmp_path):
    case_fail = _case(id="all_fail")
    data = {
        "cases": [case_fail],
        "results": [_result(case_fail, passed=False, trace=[{"step": 1}])],
        "summary": {
            "num_cases": 1, "num_passed": 0, "pass_rate": 0.0,
            "avg_total_score": 0.4,
            "avg_metrics": {k: 0.4 for k in ["tool_coverage", "task_completion", "robustness", "policy_citation", "no_fabrication", "efficiency"]},
        },
        "use_llm_judge": False,
    }
    write_report(data, str(tmp_path))
    with open(os.path.join(str(tmp_path), "report.md"), "r", encoding="utf-8") as f:
        assert "失败样本" in f.read()
