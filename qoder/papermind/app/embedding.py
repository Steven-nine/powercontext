"""向量化后端。

默认使用 DashScope 的 text-embedding-v3。未配置 API Key 时，可切换到
本地确定性哈希向量，让检索、引用、记忆与界面在零凭据下也能完整跑通。
哈希向量只反映字面重叠，不具备真实模型的语义能力，仅用于演示与自测。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import pyseekdb


class LocalHashEmbeddingFunction:
    """字符 n-gram 哈希向量，归一化到单位长度。"""

    def __init__(self, dimension: int = 384) -> None:
        if dimension <= 0:
            raise ValueError("dimension 必须为正整数")
        self.dimension = int(dimension)

    @staticmethod
    def name() -> str:
        return "local-hash"

    def __call__(self, documents):
        single = isinstance(documents, str)
        texts = [documents] if single else list(documents)
        vectors = [self._embed(str(text)) for text in texts]
        return vectors[0] if single else vectors

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for token, weight in self._tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vec))
        if norm == 0.0:
            return vec
        return [value / norm for value in vec]

    @staticmethod
    def _tokens(text: str):
        clean = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower())
        for word in clean.split():
            yield word, 1.0
            if re.search(r"[\u4e00-\u9fff]", word):
                for i in range(len(word) - 1):
                    yield word[i : i + 2], 0.5

    def get_config(self) -> dict[str, Any]:
        return {"dimension": self.dimension}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "LocalHashEmbeddingFunction":
        return LocalHashEmbeddingFunction(dimension=int(config.get("dimension", 384)))


pyseekdb.register_embedding_function(LocalHashEmbeddingFunction)
