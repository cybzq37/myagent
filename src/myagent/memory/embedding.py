"""统一嵌入模块（实现 + 提供器）

只保留一种实现：OpenAI 兼容 REST（POST {base_url}/embeddings）。
适用于 vLLM / Ollama / xinference / 阿里云 DashScope OpenAI 兼容入口等任何
实现了 OpenAI Embeddings API 的服务。

环境变量：
- EMBED_MODEL_NAME: 模型名称（必填，例如 bge-m3 / text-embedding-v3）
- EMBED_API_KEY:    API Key（vLLM 等不校验时填任意非空值）
- EMBED_BASE_URL:   服务地址（必填，例如 http://localhost:8000/v1）
"""

from typing import List, Union, Optional
import threading
import os
import numpy as np
import requests


# ==============
# 抽象与实现
# ==============

class EmbeddingModel:
    """嵌入模型基类（最小接口）"""

    def encode(self, texts: Union[str, List[str]]):
        raise NotImplementedError

    @property
    def dimension(self) -> int:
        raise NotImplementedError


class OpenAICompatibleEmbedding(EmbeddingModel):
    """OpenAI 兼容 REST Embedding

    调用 POST {base_url}/embeddings，请求体 {"model": ..., "input": [...]}，
    响应体 {"data": [{"embedding": [...]}]}。
    适配 vLLM / Ollama / xinference / DashScope OpenAI 兼容入口等。
    """

    def __init__(
        self,
        model_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        if not base_url:
            raise ValueError("EMBED_BASE_URL 未配置，OpenAI 兼容 Embedding 必须提供 base_url")
        if not model_name:
            raise ValueError("EMBED_MODEL_NAME 未配置")
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._dimension = None
        # 探测维度（顺便验证服务可达）
        test = self.encode("health_check")
        self._dimension = len(test)

    def encode(self, texts: Union[str, List[str]]):
        """调用 OpenAI 兼容 Embeddings API 把文本转向量。

        请求：POST {base_url}/embeddings
            Body: {"model": model_name, "input": ["text1", "text2", ...]}
            Header: Authorization: Bearer {api_key}
        响应：{"data": [{"embedding": [...]}, ...]}

        参数:
            texts: 单条字符串或字符串列表。单条传入时返回单个向量，
                   列表传入时返回向量列表（与输入顺序一一对应）。

        返回:
            np.ndarray（单条）或 List[np.ndarray]（多条），维度由模型决定。

        异常:
            RuntimeError: HTTP 状态码 >= 400，或返回向量数量与输入不匹配。
        """
        # 1. 标准化输入：统一转成 list 处理，single 标记用于还原返回类型
        if isinstance(texts, str):
            inputs = [texts]
            single = True
        else:
            inputs = list(texts)
            single = False

        # 2. 发送 OpenAI 兼容的 /embeddings 请求
        #    vLLM / Ollama / DashScope 等都实现了这个接口
        url = self.base_url + "/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model_name, "input": inputs}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Embedding REST 调用失败: {resp.status_code} {resp.text}"
            )

        # 3. 解析响应：data 数组里每个 item 的 embedding 字段就是向量
        data = resp.json()
        items = data.get("data") or []
        vecs = [np.array(item.get("embedding")) for item in items]

        # 4. 数量校验：服务端必须按顺序返回与输入等长的向量
        if len(vecs) != len(inputs):
            raise RuntimeError(
                f"Embedding 返回数量不匹配: 期望 {len(inputs)}, 实际 {len(vecs)}"
            )

        # 5. 还原返回类型：单条输入返回 ndarray，多条返回 List[ndarray]
        if single:
            return vecs[0]
        return vecs

    @property
    def dimension(self) -> int:
        return int(self._dimension or 0)


# ==================
# Provider（单例）
# ==================

_lock = threading.RLock()
_embedder: Optional[EmbeddingModel] = None


def _build_embedder() -> EmbeddingModel:
    model_name = os.getenv("EMBED_MODEL_NAME", "").strip()
    api_key = os.getenv("EMBED_API_KEY", "").strip() or None
    base_url = os.getenv("EMBED_BASE_URL", "").strip() or None
    return OpenAICompatibleEmbedding(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
    )


def get_text_embedder() -> EmbeddingModel:
    """获取全局共享的文本嵌入实例（线程安全单例）"""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is None:
            _embedder = _build_embedder()
        return _embedder


def get_dimension(default: int = 1024) -> int:
    """获取统一向量维度（失败回退默认值）"""
    try:
        return int(getattr(get_text_embedder(), "dimension", default))
    except Exception:
        return int(default)


def refresh_embedder() -> EmbeddingModel:
    """强制重建嵌入实例（可用于动态切换环境变量）"""
    global _embedder
    with _lock:
        _embedder = _build_embedder()
        return _embedder
