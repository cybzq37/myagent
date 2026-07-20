"""RAG (检索增强生成) 模块

合并了 GraphRAG 能力：
- loader：文件加载/分块（含PDF、语言标注、去重）
- embedding：OpenAI 兼容 REST（vLLM / Ollama / DashScope 等）
- vector search：Qdrant召回
- rank/merge：融合排序与片段合并
"""

from ..embedding import (
    EmbeddingModel,
    OpenAICompatibleEmbedding,
    get_text_embedder,
    get_dimension,
    refresh_embedder,
)
from .document import Document, DocumentProcessor
from .pipeline import (
    load_and_chunk_texts,
    build_graph_from_chunks,
    index_chunks,
    embed_query,
    search_vectors,
    rank,
    merge_snippets,
    rerank_with_cross_encoder,
    expand_neighbors_from_pool,
    compute_graph_signals_from_pool,
    merge_snippets_grouped,
    search_vectors_expanded,
    compress_ranked_items,
    tldr_summarize,
)

__all__ = [
    "EmbeddingModel",
    "OpenAICompatibleEmbedding",
    "get_text_embedder",
    "get_dimension",
    "refresh_embedder",
    "Document",
    "DocumentProcessor",
    "load_and_chunk_texts",
    "build_graph_from_chunks",
    "index_chunks",
    "embed_query",
    "search_vectors",
    "rank",
    "merge_snippets",
    "rerank_with_cross_encoder",
    "expand_neighbors_from_pool",
    "compute_graph_signals_from_pool",
    "merge_snippets_grouped",
    "search_vectors_expanded",
    "compress_ranked_items",
    "tldr_summarize",
]
