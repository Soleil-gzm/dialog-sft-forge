"""条件解析器测试：数值比较 / 字段空非空 / 复合条件 / 兜底行为。"""

from core.conditions import ConditionParser


class TestNumericCompare:
    def setup_method(self):
        self.parser = ConditionParser()
        self.case = {"积分余额": "1250", "积分余额_数值": 1250}

    def test_greater(self):
        assert self.parser.evaluate("{积分余额}大于1000", self.case)
        assert not self.parser.evaluate("{积分余额}大于1250", self.case)

    def test_less(self):
        assert self.parser.evaluate("{积分余额}小于2000", self.case)
        assert not self.parser.evaluate("{积分余额}小于1000", self.case)

    def test_equal(self):
        assert self.parser.evaluate("{积分余额}等于1250", self.case)
        assert not self.parser.evaluate("{积分余额}等于1000", self.case)

    def test_fallback_raw_value(self):
        """无 _数值 键时，从原始值中提取数字"""
        assert self.parser.evaluate("{次数}等于3", {"次数": "3次"})

    def test_missing_field(self):
        """字段缺失按 0 处理"""
        assert self.parser.evaluate("{积分余额}小于1", {})
        assert not self.parser.evaluate("{积分余额}大于0", {})


class TestFieldNullability:
    def setup_method(self):
        self.parser = ConditionParser()

    def test_not_empty_numeric(self):
        case = {"积分余额": "0", "积分余额_数值": 0}
        assert self.parser.evaluate("积分余额为空", case)
        assert not self.parser.evaluate("积分余额不为空", case)

    def test_not_empty_string(self):
        assert self.parser.evaluate("优惠券不为空", {"优惠券": "满减券"})

    def test_empty_string(self):
        assert self.parser.evaluate("备注为空", {"备注": ""})

    def test_missing_field(self):
        assert self.parser.evaluate("任意字段为空", {})


class TestCompoundAndFallback:
    def setup_method(self):
        self.parser = ConditionParser()
        self.case = {"积分余额": "1250", "积分余额_数值": 1250, "优惠券": "满减券"}

    def test_and_composition(self):
        assert self.parser.evaluate("{积分余额}大于1000 & 优惠券不为空", self.case)
        assert not self.parser.evaluate(
            "{积分余额}大于1000 & 优惠券为空", self.case
        )

    def test_empty_condition_always_true(self):
        assert self.parser.evaluate("", self.case)
        assert self.parser.evaluate(None, self.case)

    def test_unknown_token_fallback_true(self):
        """非严格模式下，未识别 token 按无条件处理"""
        assert self.parser.evaluate("随便写的条件", self.case)
