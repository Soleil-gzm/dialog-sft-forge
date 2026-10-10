"""PathGenerator 测试：demo 配置下生成路径的合法性。"""

from core.generation.config import Config, load_config, sync_config_from_prob
from core.data.data_loader import load_prob_matrix
from core.utils.path_generator import PathGenerator
from core.utils.random_service import RandomService


def _make_generator(seed: int = 42) -> PathGenerator:
    config_dict = load_config("demo/demo_config.yaml").to_dict()
    config_dict.pop("paths_cache", None)  # 测试不读写缓存文件
    config = Config(config_dict)
    prob_df, modules = load_prob_matrix("demo/data/prob.xlsx")
    config = sync_config_from_prob(config, modules)
    return PathGenerator(config, prob_df, RandomService(seed))


class TestPathValidity:
    def test_paths_start_and_end_legally(self):
        gen = _make_generator()
        terminal = set(gen.terminal_nodes)
        self_loop = set(gen.self_loop_modules)
        for _ in range(50):
            path = gen.generate_one()
            assert path
            # 自循环独占路径：语音留言重复 max_repeat 次
            if len(set(path)) == 1 and path[0] in self_loop:
                continue
            assert path[0] == gen.start_module
            assert path[-1] in terminal | self_loop

    def test_single_a_set_module(self):
        """每条路径至多包含一个 a_set 模块"""
        gen = _make_generator()
        for _ in range(50):
            path = gen.generate_one()
            assert len(set(path) & gen.a_set) <= 1

    def test_generate_reproducible_with_same_seed(self):
        paths_a = _make_generator(7).generate(5, 7, cache_path=None)
        paths_b = _make_generator(7).generate(5, 7, cache_path=None)
        assert paths_a == paths_b
