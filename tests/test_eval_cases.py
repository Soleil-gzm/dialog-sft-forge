"""评测集 schema 与加载测试。"""

import os

import pytest
import yaml

from agent.eval.case_schema import EvalCase, load_testset

TESTSET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agent", "eval", "testset.yaml"
)


def test_load_testset_returns_cases():
    cases = load_testset(TESTSET)
    assert len(cases) == 7
    assert all(isinstance(c, EvalCase) for c in cases)


def test_case_fields_populated():
    cases = load_testset(TESTSET)
    by_id = {c.id: c for c in cases}
    assert by_id["eval_normal_followup"].member_id == "M1001"
    assert "log_visit_result" in by_id["eval_normal_followup"].expected_tools
    assert by_id["eval_points_expiry"].requires_knowledge is True
    assert by_id["eval_member_not_exists"].member_id == "M9999"


def test_load_testset_unknown_field_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "x",
                        "member_id": "M1001",
                        "task": "t",
                        "expected_tools": ["query_member_profile"],
                        "typo_field": 1,
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未知字段"):
        load_testset(str(p))


def test_load_testset_missing_required_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        yaml.safe_dump({"cases": [{"id": "x", "task": "t"}]}, allow_unicode=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="缺少必填字段"):
        load_testset(str(p))


def test_load_testset_empty_expected_tools_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        yaml.safe_dump(
            {"cases": [{"id": "x", "member_id": "M1", "task": "t", "expected_tools": []}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected_tools 必须为非空列表"):
        load_testset(str(p))


def test_load_testset_duplicate_id_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "dup",
                        "member_id": "M1001",
                        "task": "t",
                        "expected_tools": ["query_member_profile"],
                    },
                    {
                        "id": "dup",
                        "member_id": "M1002",
                        "task": "t",
                        "expected_tools": ["query_member_profile"],
                    },
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="id 重复"):
        load_testset(str(p))


def test_load_testset_missing_cases_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("foo: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少 cases 列表"):
        load_testset(str(p))
