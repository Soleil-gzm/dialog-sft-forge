"""Embedding 提供者 —— 把文本转成向量。

EmbeddingProvider 是协议，交付两个实现：

1. APIEmbedding      —— 调用 OpenAI 兼容的 /embeddings 接口（仅标准库 urllib），
                        结果按文本哈希落盘缓存，避免重复请求与重复计费。
2. HashingEmbedding  —— 零依赖、离线、确定性的字面哈希向量（hashing trick）。
                        它不含真正的语义能力，仅保证「字面重叠高 → 向量接近」，
                        用于单元测试与无 embedding 端点时的兜底，使整条链路可离线跑通。

provider="auto" 的选择逻辑：配置了可用的 base_url 与 API Key 时走 API，否则回退哈希向量。
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Protocol

import numpy as np

from agent.rag.tokenizer import tokenize

HASHING_DIM = 256


class EmbeddingProvider(Protocol):
    """向量化接口：可替换后端。"""

    dim: int

    def embed(self, texts: List[str]) -> np.ndarray: ...


class HashingEmbedding:
    """字面哈希向量（离线兜底 / 单测用），不具备语义泛化能力。"""

    def __init__(self, dim: int = HASHING_DIM):
        self.dim = dim

    def embed(self, texts: List[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                digest = hashlib.md5(token.encode("utf-8")).hexdigest()
                vectors[row, int(digest, 16) % self.dim] += 1.0
        return vectors


class APIEmbedding:
    """OpenAI 兼容 /embeddings 客户端，带磁盘缓存。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 30,
        cache_path: str = "",
        batch_size: int = 32,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.cache_path = cache_path
        self.batch_size = batch_size
        self.dim = 0
        self._cache: Dict[str, List[float]] = self._load_cache()

    # ---------- 缓存 ----------

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _load_cache(self) -> Dict[str, List[float]]:
        if not self.cache_path or not os.path.isfile(self.cache_path):
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f)

    # ---------- 请求 ----------

    def _request_batch(self, texts: List[str]) -> List[List[float]]:
        payload = {"model": self.model, "input": texts, "encoding_format": "float"}
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
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
            raise RuntimeError(f"Embedding 请求失败 [{e.code}]: {detail}") from e

        # 按返回的 index 排序，保证与输入顺序一致
        items = sorted(body["data"], key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items]

    def embed(self, texts: List[str]) -> np.ndarray:
        if not self.api_key:
            raise RuntimeError("未配置 Embedding API Key")

        vectors: List[List[float]] = []
        pending: List[str] = []
        pending_keys: List[str] = []

        def flush() -> None:
            if not pending:
                return
            for key, vector in zip(pending_keys, self._request_batch(pending)):
                self._cache[key] = vector
            self._save_cache()
            pending.clear()
            pending_keys.clear()

        for text in texts:
            key = self._key(text)
            cached = self._cache.get(key)
            if cached is not None:
                flush()
                vectors.append(cached)
                continue
            pending.append(text)
            pending_keys.append(key)
            if len(pending) >= self.batch_size:
                flush()

        flush()
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.size:
            self.dim = matrix.shape[1]
        return matrix


def build_embedding_provider(config) -> EmbeddingProvider:
    """按配置构建向量化 provider。

    读取 rag.embedding.* 配置。provider 取值为 auto / api / hashing：
    auto 在缺少 base_url 或 API Key 时回退哈希向量，保证检索链路始终可跑。
    """
    provider = (config.get("rag.embedding.provider", "auto") or "auto").lower()
    base_url = config.get("rag.embedding.base_url", "") or ""
    model = config.get("rag.embedding.model", "text-embedding-3-small")
    key_env = config.get("rag.embedding.api_key_env", "AGENT_EMBEDDING_API_KEY")
    api_key = os.environ.get(key_env, "") or (config.get("rag.embedding.api_key", "") or "")
    cache_path = config.get("rag.embedding.cache_path", "")

    if provider == "hashing":
        return HashingEmbedding()

    if provider == "api":
        if not base_url or not api_key:
            raise RuntimeError(
                f"provider=api 需要配置 rag.embedding.base_url 与环境变量 {key_env}"
            )
        return APIEmbedding(base_url=base_url, model=model, api_key=api_key, cache_path=cache_path)

    # auto：能用 API 就用，否则回退哈希向量
    if base_url and api_key:
        return APIEmbedding(base_url=base_url, model=model, api_key=api_key, cache_path=cache_path)
    return HashingEmbedding()
