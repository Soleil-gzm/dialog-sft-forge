"""fill_placeholders 测试：通用占位符替换。"""

from core.generation.utterance import fill_placeholders

CASE = {
    "门店名称": "茗香茶饮",
    "积分余额": "1250",
    "随机金额": "18",
}


def test_replace_existing_fields():
    assert (
        fill_placeholders("欢迎来到{门店名称}", CASE) == "欢迎来到茗香茶饮"
    )
    assert fill_placeholders("赠送{随机金额}积分", CASE) == "赠送18积分"


def test_multiple_placeholders():
    text = "{门店名称}会员积分{积分余额}分"
    assert fill_placeholders(text, CASE) == "茗香茶饮会员积分1250分"


def test_missing_field_kept_as_is():
    assert fill_placeholders("{不存在的字段}", CASE) == "{不存在的字段}"


def test_no_placeholder():
    assert fill_placeholders("普通文本", CASE) == "普通文本"


def test_non_string_passthrough():
    assert fill_placeholders(123, CASE) == 123
    assert fill_placeholders(None, CASE) is None
