"""OpenAI 兼容的 LLM 客户端（仅依赖标准库，不引入额外依赖）。

配置读取优先级：环境变量 > 配置文件
  AGENT_BASE_URL / AGENT_API_KEY / AGENT_MODEL

兼容 OpenAI /chat/completions 协议的端点（OpenAI、DashScope、vLLM、Ollama 等）。
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# agent/core/llm_client.py -> 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env_file(path: str) -> Dict[str, str]:
    """极简 .env 解析（仅标准库）：KEY=VALUE，忽略空行与 # 注释。"""
    if not os.path.isfile(path):
        return {}
    values: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class LLMClient:
    """极简 OpenAI 兼容客户端，支持 tools（function calling）。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        temperature: float = 0.3,
        timeout: int = 60,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout

    @classmethod
    def from_config(cls, config) -> "LLMClient":
        """从 AgentConfig 构建客户端。

        取值优先级：进程环境变量 > 项目根目录 .env > 配置文件。
        .env 已被 .gitignore 忽略，不会被提交到仓库。
        """
        env_file = {
            **_load_env_file(os.path.join(_PROJECT_ROOT, ".env")),
            **_load_env_file(os.path.join(os.getcwd(), ".env")),
        }

        def resolve(name: str, default: str = "") -> str:
            return os.environ.get(name) or env_file.get(name) or default

        api_key_env = config.get("llm.api_key_env", "AGENT_API_KEY")
        return cls(
            base_url=resolve("AGENT_BASE_URL", config.get("llm.base_url", "")),
            model=resolve("AGENT_MODEL", config.get("llm.model", "")),
            api_key=resolve(api_key_env, ""),
            temperature=config.get("llm.temperature", 0.3),
            timeout=config.get("llm.timeout", 60),
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """调用 /chat/completions，返回 choices[0].message。"""
        if not self.api_key:
            raise RuntimeError("未配置 API Key，请在环境变量或 .env 中设置 AGENT_API_KEY")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"LLM 请求失败 [{e.code}]: {detail}") from e

        return body["choices"][0]["message"]
