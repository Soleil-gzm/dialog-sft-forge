"""Agent 配置加载：YAML + 点号分隔的嵌套访问。

与 scripts_general/core/generation/config.py 保持一致的读取风格，
但保持 agent/ 模块自包含，便于独立运行与演示。
"""

import os
from typing import Any, Dict, Optional

import yaml


class AgentConfig:
    """Agent 配置容器，支持 'llm.model' 这样的点号访问。"""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """支持点号分隔的嵌套访问，如 'llm.model'。"""
        value: Any = self._data
        for k in key.split("."):
            if not isinstance(value, dict) or k not in value:
                return default
            value = value[k]
        return value

    def to_dict(self) -> Dict[str, Any]:
        return self._data.copy()


def load_agent_config(config_path: str) -> AgentConfig:
    """加载 YAML 配置文件并返回 AgentConfig 对象。"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AgentConfig(data)


def resolve_path(path: str, base_dir: str) -> str:
    """把配置中的相对路径解析为基于 base_dir 的绝对路径。"""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(base_dir, path))
