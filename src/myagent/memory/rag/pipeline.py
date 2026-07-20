"""RAG Pipeline 核心流程
======================

整体阶段（顺序）：
  1. 文档加载与分块 (load_and_chunk_texts)
     - 任意格式（PDF/Office/图片/音频/文本/代码/压缩包）→ MarkItDown 转 Markdown
     - 按段落+标题栈切分，token 长度自适应，支持 overlap
     - 全局去重（按 content_hash）+ 元数据标注（doc_id/start/end/heading_path）
     - 可选：构建 Neo4j 图（Document -[HAS_CHUNK]-> Memory）

  2. 向量化与入库 (index_chunks)
     - 统一 embedder（OpenAI 兼容 REST：vLLM / Ollama / DashScope 等）
     - Markdown 预处理：去标记、保留语义，再批量 encode
     - 维度对齐：异常维度零填充/截断，批次失败自动降级到小批次重试
     - 写入 Qdrant，元数据打 RAG 标签（is_rag_data/memory_type 等）

  3. 检索 (search_vectors / search_vectors_expanded)
     - 基础：单查询 embedding → Qdrant 余弦召回 → 按 rag_namespace 过滤
     - 扩展：MQE 多查询扩展（LLM 生成等价查询）+ HyDe 假设文档检索
     - 多扩展查询结果按 memory_id 去重取最高分，最终 top_k

  4. 重排与图信号 (rerank_with_cross_encoder / compute_graph_signals_from_pool / rank)
     - Cross-Encoder 重排（query-doc 对打分）
     - 图信号：同文档密度分 + 邻近位置分（基于 start/end 字符偏移的滑动窗口）
     - 最终分 = w_vector * 向量分 + w_graph * 图分

  5. 后处理 (merge_snippets / merge_snippets_grouped / compress_ranked_items / tldr_summarize)
     - 简单拼接 / 按文档分组并加引用 [n] / 同文档片段压缩合并 / LLM TLDR 总结

入口封装：create_rag_pipeline() 返回 {store, add_documents, search, ...} 字典。
"""
from typing import List, Dict, Optional, Any
import os
import hashlib
import sqlite3
import time
import json
from ..embedding import get_text_embedder, get_dimension
from ..storage.qdrant_store import QdrantVectorStore


def _get_markitdown_instance():
    """
    Get a configured MarkItDown instance for document conversion.
    """
    try:
        from markitdown import MarkItDown
        return MarkItDown()
    except ImportError:
        print("[WARNING] MarkItDown not available. Install with: pip install markitdown")
        return None


def _is_markitdown_supported_format(path: str) -> bool:
    """
    判断文件格式是否被 MarkItDown 支持。
    覆盖：PDF / Office 文档 / 图片(OCR) / 音频(转写) / 文本格式 / 压缩包 / 代码等。
    """
    ext = (os.path.splitext(path)[1] or '').lower()
    supported_formats = {
        # Documents
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        # Text formats
        '.txt', '.md', '.csv', '.json', '.xml', '.html', '.htm',
        # Images (OCR + metadata)
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
        # Audio (transcription + metadata) 
        '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg',
        # Archives
        '.zip', '.tar', '.gz', '.rar',
        # Code files
        '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.css', '.scss',
        # Other text
        '.log', '.conf', '.ini', '.cfg', '.yaml', '.yml', '.toml'
    }
    return ext in supported_formats


def _convert_to_markdown(path: str) -> str:
    """
    通用文档读取入口：任意格式 → Markdown 文本。
    - PDF 走增强流程（_enhanced_pdf_processing），做噪音清理和段落重组
    - 其他格式走 MarkItDown 直接转换
    - 失败时降级到 _fallback_text_reader（utf-8 / latin-1 粗读）
    """
    if not os.path.exists(path):
        return ""
    
    # 对PDF文件使用增强处理
    ext = (os.path.splitext(path)[1] or '').lower()
    if ext == '.pdf':
        return _enhanced_pdf_processing(path)
    
    # 其他格式使用原有MarkItDown
    md_instance = _get_markitdown_instance()
    if md_instance is None:
        return _fallback_text_reader(path)
    
    try:
        result = md_instance.convert(path)
        text = getattr(result, "text_content", None)
        if isinstance(text, str) and text.strip():
            return text
        return ""
    except Exception as e:
        print(f"[WARNING] MarkItDown failed for {path}: {e}")
        return _fallback_text_reader(path)

def _enhanced_pdf_processing(path: str) -> str:
    """
    PDF 增强处理：MarkItDown 提取 → _post_process_pdf_text 清理重组。
    专门处理 PDF 常见的页眉页脚噪音、短行碎片、段落断裂问题。
    """
    print(f"[RAG] Using enhanced PDF processing for: {path}")
    
    # 使用原有MarkItDown提取
    md_instance = _get_markitdown_instance()
    if md_instance is None:
        return _fallback_text_reader(path)
    
    try:
        result = md_instance.convert(path)
        raw_text = getattr(result, "text_content", None)
        if not raw_text or not raw_text.strip():
            return ""
        
        # 后处理：清理和重组文本
        cleaned_text = _post_process_pdf_text(raw_text)
        print(f"[RAG] PDF post-processing completed: {len(raw_text)} -> {len(cleaned_text)} chars")
        return cleaned_text
        
    except Exception as e:
        print(f"[WARNING] Enhanced PDF processing failed for {path}: {e}")
        return _fallback_text_reader(path)

def _post_process_pdf_text(text: str) -> str:
    """
    PDF 文本后处理三步走：
    1. 按行清理：去掉单字符噪音行、纯数字页码行、常见页眉页脚词
    2. 短行合并：把 <60 字的短行和下一行合并（避免换行打断句子）
    3. 段落重组：以标题/冒号结尾/长句为段落起点，重组段落结构
    """
    import re
    
    # 1. 按行分割并清理
    lines = text.splitlines()
    cleaned_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 移除单个字符的行（通常是噪音）
        if len(line) <= 2 and not line.isdigit():
            continue
            
        # 移除明显的页眉页脚噪音
        if re.match(r'^\d+$', line):  # 纯数字行（页码）
            continue
        if line.lower() in ['github', 'project', 'forks', 'stars', 'language']:
            continue
            
        cleaned_lines.append(line)
    
    # 2. 智能合并短行
    merged_lines = []
    i = 0
    
    while i < len(cleaned_lines):
        current_line = cleaned_lines[i]
        
        # 如果当前行很短，尝试与下一行合并
        if len(current_line) < 60 and i + 1 < len(cleaned_lines):
            next_line = cleaned_lines[i + 1]
            
            # 合并条件：都是内容，不是标题
            if (not current_line.endswith('：') and 
                not current_line.endswith(':') and
                not current_line.startswith('#') and
                not next_line.startswith('#') and
                len(next_line) < 120):
                
                merged_line = current_line + " " + next_line
                merged_lines.append(merged_line)
                i += 2  # 跳过下一行
                continue
        
        merged_lines.append(current_line)
        i += 1
    
    # 3. 重新组织段落
    paragraphs = []
    current_paragraph = []
    
    for line in merged_lines:
        # 检查是否是新段落的开始
        if (line.startswith('#') or  # 标题
            line.endswith('：') or   # 中文冒号结尾
            line.endswith(':') or    # 英文冒号结尾
            len(line) > 150 or       # 长句通常是段落开始
            not current_paragraph):  # 第一行
            
            # 保存当前段落
            if current_paragraph:
                paragraphs.append(' '.join(current_paragraph))
                current_paragraph = []
            
            paragraphs.append(line)
        else:
            current_paragraph.append(line)
    
    # 添加最后一个段落
    if current_paragraph:
        paragraphs.append(' '.join(current_paragraph))
    
    return '\n\n'.join(paragraphs)


def _fallback_text_reader(path: str) -> str:
    """
    Simple fallback reader for basic text files when MarkItDown is unavailable.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        try:
            with open(path, 'r', encoding='latin-1', errors='ignore') as f:
                return f.read()
        except Exception:
            return ""


def _detect_lang(sample: str) -> str:
    try:
        from langdetect import detect
        return detect(sample[:1000]) if sample else "unknown"
    except Exception:
        return "unknown"


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or
        0x3400 <= code <= 0x4DBF or
        0x20000 <= code <= 0x2A6DF or
        0x2A700 <= code <= 0x2B73F or
        0x2B740 <= code <= 0x2B81F or
        0x2B820 <= code <= 0x2CEAF or
        0xF900 <= code <= 0xFAFF
    )


def _approx_token_len(text: str) -> int:
    # 近似 token 估计：CJK 字符按 1 token，其他按空白分词计数
    # 用于分块时快速估算长度，避免引入 tiktoken 的开销
    cjk = sum(1 for ch in text if _is_cjk(ch))
    non_cjk_tokens = len([t for t in text.split() if t])
    return cjk + non_cjk_tokens


def _split_paragraphs_with_headings(text: str) -> List[Dict]:
    """
    按标题栈切分段落，保留标题层级路径。
    维护 heading_stack（如 ["第一章", "1.1 概述"]），遇到 # 标题时压栈/弹栈，
    每个段落记录所属的 heading_path（"第一章 > 1.1 概述"）和字符偏移 [start, end)。
    """
    lines = text.splitlines()
    heading_stack: List[str] = []
    paragraphs: List[Dict] = []
    buf: List[str] = []
    char_pos = 0
    def flush_buf(end_pos: int):
        if not buf:
            return
        content = "\n".join(buf).strip()
        if not content:
            return
        paragraphs.append({
            "content": content,
            "heading_path": " > ".join(heading_stack) if heading_stack else None,
            "start": max(0, end_pos - len(content)),
            "end": end_pos,
        })
    for ln in lines:
        raw = ln
        if raw.strip().startswith("#"):
            # heading line
            flush_buf(char_pos)
            level = len(raw) - len(raw.lstrip('#'))
            title = raw.lstrip('#').strip()
            if level <= 0:
                level = 1
            if level <= len(heading_stack):
                heading_stack = heading_stack[:level-1]
            heading_stack.append(title)
            char_pos += len(raw) + 1
            continue
        # paragraph accumulation
        if raw.strip() == "":
            flush_buf(char_pos)
            buf = []
        else:
            buf.append(raw)
        char_pos += len(raw) + 1
    flush_buf(char_pos)
    if not paragraphs:
        paragraphs = [{"content": text, "heading_path": None, "start": 0, "end": len(text)}]
    return paragraphs


def _chunk_paragraphs(paragraphs: List[Dict], chunk_tokens: int, overlap_tokens: int) -> List[Dict]:
    """
    按目标 token 数打包段落为 chunk，支持尾部 overlap。
    - 累积段落直到超过 chunk_tokens，超限则输出当前 chunk
    - overlap：保留上一 chunk 尾部的若干段落，作为下一 chunk 的开头，保证上下文连续
    - 每个 chunk 记录起止字符偏移和最近的 heading_path
    """
    chunks: List[Dict] = []
    cur: List[Dict] = []
    cur_tokens = 0
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        p_tokens = _approx_token_len(p["content"]) or 1
        if cur_tokens + p_tokens <= chunk_tokens or not cur:
            cur.append(p)
            cur_tokens += p_tokens
            i += 1
        else:
            # emit current chunk
            content = "\n\n".join(x["content"] for x in cur)
            start = cur[0]["start"]
            end = cur[-1]["end"]
            heading_path = next((x["heading_path"] for x in reversed(cur) if x.get("heading_path")), None)
            chunks.append({
                "content": content,
                "start": start,
                "end": end,
                "heading_path": heading_path,
            })
            # build overlap by keeping tail tokens
            if overlap_tokens > 0 and cur:
                kept: List[Dict] = []
                kept_tokens = 0
                for x in reversed(cur):
                    t = _approx_token_len(x["content"]) or 1
                    if kept_tokens + t > overlap_tokens:
                        break
                    kept.append(x)
                    kept_tokens += t
                cur = list(reversed(kept))
                cur_tokens = kept_tokens
            else:
                cur = []
                cur_tokens = 0
    if cur:
        content = "\n\n".join(x["content"] for x in cur)
        start = cur[0]["start"]
        end = cur[-1]["end"]
        heading_path = next((x["heading_path"] for x in reversed(cur) if x.get("heading_path")), None)
        chunks.append({
            "content": content,
            "start": start,
            "end": end,
            "heading_path": heading_path,
        })
    return chunks


def load_and_chunk_texts(paths: List[str], chunk_size: int = 800, chunk_overlap: int = 100, namespace: Optional[str] = None, source_label: str = "rag") -> List[Dict]:
    """
    【阶段 1 主入口】文档加载与分块。
    流程：多格式转 Markdown → 标题感知段落切分 → token 自适应分块 → 全局去重 → 元数据标注。
    每个 chunk 生成稳定 id（doc_id + start + end + content_hash 的 md5），
    元数据含 source_path/doc_id/lang/start/end/content_hash/namespace/heading_path 等，
    用于后续检索、图信号计算和引用定位。
    """
    print(f"[RAG] Universal loader start: files={len(paths)} chunk_size={chunk_size} overlap={chunk_overlap} ns={namespace or 'default'}")
    chunks: List[Dict] = []
    seen_hashes = set()
    
    for path in paths:
        if not os.path.exists(path):
            print(f"[WARNING] File not found: {path}")
            continue
            
        print(f"[RAG] Processing: {path}")
        ext = (os.path.splitext(path)[1] or '').lower()
        
        # Convert to markdown using MarkItDown
        markdown_text = _convert_to_markdown(path)
        if not markdown_text.strip():
            print(f"[WARNING] No content extracted from: {path}")
            continue
        
        lang = _detect_lang(markdown_text)
        doc_id = hashlib.md5(f"{path}|{len(markdown_text)}".encode('utf-8')).hexdigest()
        
        # Always use markdown-aware chunking for better structure preservation
        para = _split_paragraphs_with_headings(markdown_text)
        token_chunks = _chunk_paragraphs(para, chunk_tokens=max(1, chunk_size), overlap_tokens=max(0, chunk_overlap))
        
        for ch in token_chunks:
            content = ch["content"]
            start = ch.get("start", 0)
            end = ch.get("end", start + len(content))
            norm = content.strip()
            if not norm:
                continue
                
            content_hash = hashlib.md5(norm.encode('utf-8')).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            
            chunk_id = hashlib.md5(f"{doc_id}|{start}|{end}|{content_hash}".encode('utf-8')).hexdigest()
            chunks.append({
                "id": chunk_id,
                "content": content,
                "metadata": {
                    "source_path": path,
                    "file_ext": ext,
                    "doc_id": doc_id,
                    "lang": lang,
                    "start": start,
                    "end": end,
                    "content_hash": content_hash,
                    "namespace": namespace or "default",
                    "source": source_label,
                    "external": True,
                    "heading_path": ch.get("heading_path"),
                    "format": "markdown",  # Mark all content as markdown-processed
                },
            })
            
    print(f"[RAG] Universal loader done: total_chunks={len(chunks)}")
    return chunks


def build_graph_from_chunks(neo4j, chunks: List[Dict]) -> None:
    """
    【可选】把 chunks 写入 Neo4j 图：Document -[HAS_CHUNK]-> Memory。
    每个 doc 创建一个 Document 节点，每个 chunk 创建一个 Memory 节点，
    并建立 HAS_CHUNK 关系。用于后续 GraphRAG 的图信号计算。
    """
    created_docs = set()
    for ch in chunks:
        mem_id = ch["id"]
        meta = ch.get("metadata", {})
        source_path = meta.get("source_path")
        doc_id = meta.get("doc_id")
        if doc_id and doc_id not in created_docs:
            created_docs.add(doc_id)
            try:
                neo4j.add_entity(
                    entity_id=doc_id,
                    name=os.path.basename(source_path or doc_id),
                    entity_type="Document",
                    properties={"source_path": source_path, "lang": meta.get("lang")}
                )
            except Exception:
                pass
        try:
            neo4j.add_entity(entity_id=mem_id, name=mem_id, entity_type="Memory", properties={
                "source_path": source_path,
                "doc_id": doc_id,
                "start": meta.get("start"),
                "end": meta.get("end"),
            })
        except Exception:
            pass
        if doc_id:
            try:
                neo4j.add_relationship(from_id=doc_id, to_id=mem_id, rel_type="HAS_CHUNK", properties={})
            except Exception:
                pass


def _preprocess_markdown_for_embedding(text: str) -> str:
    """
    嵌入前的 Markdown 预处理：去掉标记符号但保留语义文本。
    处理：标题井号 / 链接 URL / 加粗斜体 / 行内代码 / 代码块 / 多余空白。
    目的：减少标记噪音对 embedding 质量的干扰。
    """
    import re
    
    # Remove markdown headers symbols but keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Remove markdown links but keep the text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Remove markdown emphasis markers
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # italic
    text = re.sub(r'`([^`]+)`', r'\1', text)        # inline code
    
    # Remove markdown code blocks but keep content
    text = re.sub(r'```[^\n]*\n([\s\S]*?)```', r'\1', text)
    
    # Remove excessive whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    
    return text.strip()


def _create_default_vector_store(dimension: int = None) -> QdrantVectorStore:
    """
    创建默认 Qdrant 向量库连接（通过 QdrantConnectionManager 单例管理）。
    collection 名固定为 "hello_agents_rag_vectors"，距离度量 cosine。
    dimension 从 embedder 探测，失败回退 1024（bge-m3 默认维度）。
    """
    if dimension is None:
        dimension = get_dimension(1024)
    
    # Check for Qdrant configuration
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    
    # 使用连接管理器
    from ..storage.qdrant_store import QdrantConnectionManager
    return QdrantConnectionManager.get_instance(
        url=qdrant_url,
        api_key=qdrant_api_key,
        collection_name="hello_agents_rag_vectors",
        vector_size=dimension,
        distance="cosine"
    )


# Cache functions removed - using unified embedder with internal caching


def index_chunks(
    store = None,
    chunks: List[Dict] = None,
    cache_db: Optional[str] = None,
    batch_size: int = 64,
    rag_namespace: str = "default"
) -> None:
    """
    【阶段 2 主入口】向量化并写入 Qdrant。
    流程：
      1. 统一 embedder 批量编码（先 Markdown 预处理去标记）
      2. 维度对齐：异常维度零填充或截断
      3. 批次失败降级：大批次 → 小批次(8)重试，仍失败用零向量占位
      4. 元数据打 RAG 标签（memory_type=rag_chunk / is_rag_data=True / data_source=rag_pipeline）
      5. store.add_vectors 写入 Qdrant
    返回 None，失败抛 RuntimeError。
    """
    if not chunks:
        print("[RAG] No chunks to index")
        return
    
    # Use unified embedding from embedding module
    embedder = get_text_embedder()
    dimension = get_dimension(1024)
    
    # Create default Qdrant store if not provided
    if store is None:
        store = _create_default_vector_store(dimension)
        print(f"[RAG] Created default Qdrant store with dimension {dimension}")
    
    # Preprocess markdown texts for better embeddings
    processed_texts = []
    for c in chunks:
        raw_content = c["content"]
        processed_content = _preprocess_markdown_for_embedding(raw_content)
        processed_texts.append(processed_content)
    
    print(f"[RAG] Embedding start: total_texts={len(processed_texts)} batch_size={batch_size}")
    
    # Batch encoding with unified embedder
    vecs: List[List[float]] = []
    for i in range(0, len(processed_texts), batch_size):
        part = processed_texts[i:i+batch_size]
        try:
            # Use unified embedder directly (handles caching internally)
            part_vecs = embedder.encode(part)
            
            # Normalize to List[List[float]]
            if not isinstance(part_vecs, list):
                # 单个numpy数组转为列表中的列表
                if hasattr(part_vecs, "tolist"):
                    part_vecs = [part_vecs.tolist()]
                else:
                    part_vecs = [list(part_vecs)]
            else:
                # 检查是否是嵌套列表
                if part_vecs and not isinstance(part_vecs[0], (list, tuple)) and hasattr(part_vecs[0], "__len__"):
                    # numpy数组列表 -> 转换每个数组
                    normalized_vecs = []
                    for v in part_vecs:
                        if hasattr(v, "tolist"):
                            normalized_vecs.append(v.tolist())
                        else:
                            normalized_vecs.append(list(v))
                    part_vecs = normalized_vecs
                elif part_vecs and not isinstance(part_vecs[0], (list, tuple)):
                    # 单个向量被误判为列表，实际应该包装成[[...]]
                    if hasattr(part_vecs, "tolist"):
                        part_vecs = [part_vecs.tolist()]
                    else:
                        part_vecs = [list(part_vecs)]
            
            for v in part_vecs:
                try:
                    # 确保向量是float列表
                    if hasattr(v, "tolist"):
                        v = v.tolist()
                    v_norm = [float(x) for x in v]
                    if len(v_norm) != dimension:
                        print(f"[WARNING] 向量维度异常: 期望{dimension}, 实际{len(v_norm)}")
                        # 用零向量填充或截断
                        if len(v_norm) < dimension:
                            v_norm.extend([0.0] * (dimension - len(v_norm)))
                        else:
                            v_norm = v_norm[:dimension]
                    vecs.append(v_norm)
                except Exception as e:
                    print(f"[WARNING] 向量转换失败: {e}, 使用零向量")
                    vecs.append([0.0] * dimension)
                
        except Exception as e:
            print(f"[WARNING] Batch {i} encoding failed: {e}")
            print(f"[RAG] Retrying batch {i} with smaller chunks...")
            
            # 尝试重试：将批次分解为更小的块
            success = False
            for j in range(0, len(part), 8):  # 更小的批次
                small_part = part[j:j+8]
                try:
                    import time
                    time.sleep(2)  # 等待2秒避免频率限制
                    
                    small_vecs = embedder.encode(small_part)
                    # Normalize to List[List[float]]
                    if isinstance(small_vecs, list) and small_vecs and not isinstance(small_vecs[0], list):
                        small_vecs = [small_vecs]
                    
                    for v in small_vecs:
                        if hasattr(v, "tolist"):
                            v = v.tolist()
                        try:
                            v_norm = [float(x) for x in v]
                            if len(v_norm) != dimension:
                                print(f"[WARNING] 向量维度异常: 期望{dimension}, 实际{len(v_norm)}")
                                if len(v_norm) < dimension:
                                    v_norm.extend([0.0] * (dimension - len(v_norm)))
                                else:
                                    v_norm = v_norm[:dimension]
                            vecs.append(v_norm)
                            success = True
                        except Exception as e2:
                            print(f"[WARNING] 小批次向量转换失败: {e2}")
                            vecs.append([0.0] * dimension)
                except Exception as e2:
                    print(f"[WARNING] 小批次 {j//8} 仍然失败: {e2}")
                    # 为这个小批次创建零向量
                    for _ in range(len(small_part)):
                        vecs.append([0.0] * dimension)
            
            if not success:
                print(f"[ERROR] 批次 {i} 完全失败，使用零向量")
        
        print(f"[RAG] Embedding progress: {min(i+batch_size, len(processed_texts))}/{len(processed_texts)}")
    
    # Prepare metadata with RAG tags
    metas: List[Dict] = []
    ids: List[str] = []
    for ch in chunks:
        meta = {
            "memory_id": ch["id"],
            "user_id": "rag_user",
            "memory_type": "rag_chunk",
            "content": ch["content"],  # Keep original markdown content
            "data_source": "rag_pipeline",  # RAG identification tag
            "rag_namespace": rag_namespace,
            "is_rag_data": True,  # Clear RAG data marker
        }
        # Merge chunk metadata
        meta.update(ch.get("metadata", {}))
        metas.append(meta)
        ids.append(ch["id"])
    
    print(f"[RAG] Qdrant upsert start: n={len(vecs)}")
    success = store.add_vectors(vectors=vecs, metadata=metas, ids=ids)
    if success:
        print(f"[RAG] Qdrant upsert done: {len(vecs)} vectors indexed")
    else:
        print(f"[RAG] Qdrant upsert failed")
        raise RuntimeError("Failed to index vectors to Qdrant")


def embed_query(query: str) -> List[float]:
    """
    查询向量化：用统一 embedder 编码单条 query，返回 List[float]。
    异常时返回零向量兜底，保证检索流程不中断。
    """
    embedder = get_text_embedder()
    dimension = get_dimension(1024)
    try:
        vec = embedder.encode(query)
        
        # Normalize to List[float]
        if hasattr(vec, "tolist"):
            vec = vec.tolist()
        
        # 处理嵌套列表情况
        if isinstance(vec, list) and vec and isinstance(vec[0], (list, tuple)):
            vec = vec[0]  # Extract first vector if nested
        
        # 转换为float列表
        result = [float(x) for x in vec]
        
        # 检查维度
        if len(result) != dimension:
            print(f"[WARNING] Query向量维度异常: 期望{dimension}, 实际{len(result)}")
            # 用零向量填充或截断
            if len(result) < dimension:
                result.extend([0.0] * (dimension - len(result)))
            else:
                result = result[:dimension]
        
        return result
    except Exception as e:
        print(f"[WARNING] Query embedding failed: {e}")
        # Return zero vector as fallback
        return [0.0] * dimension


def search_vectors(
    store = None,
    query: str = "",
    top_k: int = 8,
    rag_namespace: Optional[str] = None,
    only_rag_data: bool = True,
    score_threshold: Optional[float] = None
) -> List[Dict]:
    """
    【阶段 3 基础检索】单查询向量召回。
    流程：query → embed_query → Qdrant 余弦相似搜索 → 按 rag_namespace / is_rag_data 过滤。
    返回 [{id, score, metadata, ...}]，按相似度降序。
    """
    if not query:
        return []
    
    # Create default store if not provided
    if store is None:
        store = _create_default_vector_store()
    
    # Embed query with unified embedder
    qv = embed_query(query)
    
    # Build filter for RAG data
    where = {"memory_type": "rag_chunk"}
    if only_rag_data:
        where["is_rag_data"] = True
        where["data_source"] = "rag_pipeline"
    if rag_namespace:
        where["rag_namespace"] = rag_namespace
    
    try:
        return store.search_similar(
            query_vector=qv, 
            limit=top_k, 
            score_threshold=score_threshold, 
            where=where
        )
    except Exception as e:
        print(f"[WARNING] RAG search failed: {e}")
        return []


def _prompt_mqe(query: str, n: int) -> List[str]:
    """MQE 多查询扩展：让 LLM 把原查询改写成 n 个语义等价/互补的查询，用于多路召回。"""
    try:
        from ...core.llm import HelloAgentsLLM
        llm = HelloAgentsLLM()
        prompt = [
            {"role": "system", "content": "你是检索查询扩展助手。生成语义等价或互补的多样化查询。使用中文，简短，避免标点。"},
            {"role": "user", "content": f"原始查询：{query}\n请给出{n}个不同表述的查询，每行一个。"}
        ]
        text = llm.invoke(prompt)
        lines = [ln.strip("- \t") for ln in (text or "").splitlines()]
        outs = [ln for ln in lines if ln]
        return outs[:n] or [query]
    except Exception:
        return [query]


def _prompt_hyde(query: str) -> Optional[str]:
    """HyDe 假设文档检索：让 LLM 先写一段可能的答案段落，用这段假答案去向量检索，召回更贴近答案语义的文档。"""
    try:
        from ...core.llm import HelloAgentsLLM
        llm = HelloAgentsLLM()
        prompt = [
            {"role": "system", "content": "根据用户问题，先写一段可能的答案性段落，用于向量检索的查询文档（不要分析过程）。"},
            {"role": "user", "content": f"问题：{query}\n请直接写一段中等长度、客观、包含关键术语的段落。"}
        ]
        return llm.invoke(prompt)
    except Exception:
        return None


def search_vectors_expanded(
    store = None,
    query: str = "",
    top_k: int = 8,
    rag_namespace: Optional[str] = None,
    only_rag_data: bool = True,
    score_threshold: Optional[float] = None,
    enable_mqe: bool = False,
    mqe_expansions: int = 2,
    enable_hyde: bool = False,
    candidate_pool_multiplier: int = 4,
) -> List[Dict]:
    """
    【阶段 3 扩展检索】支持 MQE + HyDe 的多路召回。
    流程：
      1. 构造扩展查询集合 = [原query] + MQE 改写 + HyDe 假答案
      2. 每个扩展查询独立召回 per = pool / len(expansions) 条
      3. 按 memory_id 聚合去重，同 id 取最高分
      4. 按分数降序取 top_k 返回
    candidate_pool_multiplier：候选池放大倍数（top_k * multiplier），先召回更多再裁剪。
    """
    if not query:
        return []
    
    # Create default store if not provided
    if store is None:
        store = _create_default_vector_store()
    
    # expansions
    expansions: List[str] = [query]
    
    if enable_mqe and mqe_expansions > 0:
        expansions.extend(_prompt_mqe(query, mqe_expansions))
    if enable_hyde:
        hyde_text = _prompt_hyde(query)
        if hyde_text:
            expansions.append(hyde_text)

    # unique and trim
    uniq: List[str] = []
    for e in expansions:
        if e and e not in uniq:
            uniq.append(e)
    expansions = uniq[: max(1, len(uniq))]

    # distribute pool per expansion
    pool = max(top_k * candidate_pool_multiplier, 20)
    per = max(1, pool // max(1, len(expansions)))

    # Build filter for RAG data
    where = {"memory_type": "rag_chunk"}
    if only_rag_data:
        where["is_rag_data"] = True
        where["data_source"] = "rag_pipeline"
    if rag_namespace:
        where["rag_namespace"] = rag_namespace

    # collect hits across expansions
    agg: Dict[str, Dict] = {}
    for q in expansions:
        qv = embed_query(q)
        hits = store.search_similar(query_vector=qv, limit=per, score_threshold=score_threshold, where=where)
        for h in hits:
            mid = h.get("metadata", {}).get("memory_id", h.get("id"))
            s = float(h.get("score", 0.0))
            if mid not in agg or s > float(agg[mid].get("score", 0.0)):
                agg[mid] = h
    # return top by score
    merged = list(agg.values())
    merged.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return merged[:top_k]


def _try_load_cross_encoder(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder(model_name)
    except Exception:
        return None


def rerank_with_cross_encoder(query: str, items: List[Dict], model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", top_k: int = 10) -> List[Dict]:
    """
    【阶段 4 重排】用 Cross-Encoder 对 (query, doc) 对打分重排。
    与 bi-encoder（向量检索）的区别：Cross-Encoder 把 query 和 doc 拼接后联合编码，
    能捕捉更细粒度的语义交互，精度更高但速度慢，所以只对 top-N 候选重排。
    模型不可用时直接返回原序 top_k。
    """
    ce = _try_load_cross_encoder(model_name)
    if ce is None or not items:
        return items[:top_k]
    pairs = [[query, it.get("content", "")] for it in items]
    try:
        scores = ce.predict(pairs)
        for it, s in zip(items, scores):
            it["rerank_score"] = float(s)
        items.sort(key=lambda x: x.get("rerank_score", x.get("score", 0.0)), reverse=True)
        return items[:top_k]
    except Exception:
        return items[:top_k]


def compute_graph_signals_from_pool(vector_hits: List[Dict], same_doc_weight: float = 1.0, proximity_weight: float = 1.0, proximity_window_chars: int = 1600) -> Dict[str, float]:
    """
    【阶段 4 图信号】基于文档结构计算图信号分，返回 {memory_id: score}。
    两个信号：
      - 同文档密度分（same_doc_weight）：同文档命中越多，说明该文档越相关，
        该文档内所有 hit 的 density = 命中数 / 最大文档命中数
      - 邻近位置分（proximity_weight）：同一文档内 hit 之间字符距离越近，
        互相加分的权重越大（线性衰减，距离超过 proximity_window_chars 不加分）
    最终归一化到 [0, 1]。用于 rank() 中和向量分加权融合。
    """

    # group by doc
    by_doc: Dict[str, List[Dict]] = {}
    for h in vector_hits:
        meta = h.get("metadata", {})
        did = meta.get("doc_id")
        if not did:
            # fall back to memory_id grouping if doc missing
            did = meta.get("memory_id") or h.get("id")
        by_doc.setdefault(did, []).append(h)

    # same-doc density score
    doc_counts = {d: len(arr) for d, arr in by_doc.items()}
    max_count = max(doc_counts.values()) if doc_counts else 1

    # proximity score per hit within same doc
    graph_signal: Dict[str, float] = {}
    for did, arr in by_doc.items():
        arr.sort(key=lambda x: x.get("metadata", {}).get("start", 0))
        # precompute density
        density = doc_counts.get(did, 1) / max_count
        # proximity accumulation
        for i, h in enumerate(arr):
            mid = h.get("metadata", {}).get("memory_id", h.get("id"))
            pos_i = h.get("metadata", {}).get("start", 0)
            prox_acc = 0.0
            # look around neighbors within window
            # two-pointer expansion
            # left
            j = i - 1
            while j >= 0:
                pos_j = arr[j].get("metadata", {}).get("start", 0)
                dist = abs(pos_i - pos_j)
                if dist > proximity_window_chars:
                    break
                prox_acc += max(0.0, 1.0 - (dist / max(1.0, float(proximity_window_chars))))
                j -= 1
            # right
            j = i + 1
            while j < len(arr):
                pos_j = arr[j].get("metadata", {}).get("start", 0)
                dist = abs(pos_i - pos_j)
                if dist > proximity_window_chars:
                    break
                prox_acc += max(0.0, 1.0 - (dist / max(1.0, float(proximity_window_chars))))
                j += 1
            # combine
            score = same_doc_weight * density + proximity_weight * prox_acc
            graph_signal[mid] = graph_signal.get(mid, 0.0) + score

    # normalize to [0,1]
    if graph_signal:
        max_v = max(graph_signal.values())
        if max_v > 0:
            for k in list(graph_signal.keys()):
                graph_signal[k] = graph_signal[k] / max_v
    return graph_signal


def rank(vector_hits: List[Dict], graph_signals: Optional[Dict[str, float]] = None, w_vector: float = 0.7, w_graph: float = 0.3) -> List[Dict]:
    """
    【阶段 4 融合排序】最终分 = w_vector * 向量分 + w_graph * 图信号分。
    默认向量分权重 0.7，图分权重 0.3。输出统一结构 {memory_id, score, vector_score, graph_score, content, metadata}。
    """
    items: List[Dict] = []
    graph_signals = graph_signals or {}
    for h in vector_hits:
        mid = h.get("metadata", {}).get("memory_id", h.get("id"))
        g = float(graph_signals.get(mid, 0.0))
        v = float(h.get("score", 0.0))
        score = w_vector * v + w_graph * g
        items.append({
            "memory_id": mid,
            "score": score,
            "vector_score": v,
            "graph_score": g,
            "content": h.get("metadata", {}).get("content", ""),
            "metadata": h.get("metadata", {}),
        })
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def merge_snippets(ranked_items: List[Dict], max_chars: int = 1200) -> str:
    """【阶段 5】简单拼接：按排名顺序拼接片段文本，超过 max_chars 截断。"""
    out: List[str] = []
    total = 0
    for it in ranked_items:
        text = it.get("content", "").strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            remain = max_chars - total
            if remain <= 0:
                break
            out.append(text[:remain])
            total += remain
            break
        out.append(text)
        total += len(text)
    return "\n\n".join(out)


def expand_neighbors_from_pool(selected: List[Dict], pool: List[Dict], neighbors: int = 1, max_additions: int = 5) -> List[Dict]:
    """
    【阶段 5 邻居扩展】从候选池里补充同文档的相邻片段。
    逻辑：对每个已选片段，在同一文档内按 start 偏移找前后 neighbors 个相邻片段，
    补充进来（最多 max_additions 个），保证上下文完整。最后按分数重排。
    """
    if not selected or not pool or neighbors <= 0:
        return selected
    # index pool by doc_id and sort by start
    by_doc: Dict[str, List[Dict]] = {}
    for it in pool:
        meta = it.get("metadata", {})
        did = meta.get("doc_id")
        if not did:
            continue
        by_doc.setdefault(did, []).append(it)
    for did, arr in by_doc.items():
        arr.sort(key=lambda x: (x.get("metadata", {}).get("start", 0)))
    selected_ids = set(it.get("memory_id") for it in selected)
    additions: List[Dict] = []
    for it in selected:
        meta = it.get("metadata", {})
        did = meta.get("doc_id")
        if not did or did not in by_doc:
            continue
        arr = by_doc[did]
        # find index
        try:
            idx = next(i for i, x in enumerate(arr) if x.get("memory_id") == it.get("memory_id"))
        except StopIteration:
            continue
        for offset in range(1, neighbors + 1):
            for j in (idx - offset, idx + offset):
                if 0 <= j < len(arr):
                    cand = arr[j]
                    mid = cand.get("memory_id")
                    if mid not in selected_ids:
                        additions.append(cand)
                        selected_ids.add(mid)
                        if len(additions) >= max_additions:
                            break
            if len(additions) >= max_additions:
                break
        if len(additions) >= max_additions:
            break
    # keep relative order by score
    extended = list(selected) + additions
    extended.sort(key=lambda x: (x.get("rerank_score", x.get("score", 0.0))), reverse=True)
    return extended


def merge_snippets_grouped(ranked_items: List[Dict], max_chars: int = 1200, include_citations: bool = True) -> str:
    """
    【阶段 5 分组拼接】按文档聚合后输出，并自动添加引用标记 [n]。
    流程：
      1. 按 doc_id 分组，每文档累加分数排序
      2. 文档内按 start 偏移排序，保证上下文顺序
      3. 每个片段末尾加 [n] 引用标记，并在文末生成 References 列表
      4. 超 max_chars 截断
    适合需要溯源到原文位置的问答场景。
    """
    # Group by doc_id and aggregate doc score
    by_doc: Dict[str, List[Dict]] = {}
    doc_score: Dict[str, float] = {}
    for it in ranked_items:
        meta = it.get("metadata", {})
        did = meta.get("doc_id") or meta.get("source_path") or "unknown"
        by_doc.setdefault(did, []).append(it)
        doc_score[did] = doc_score.get(did, 0.0) + float(it.get("score", 0.0))
    # Sort docs by aggregate score
    ordered_docs = sorted(by_doc.keys(), key=lambda d: doc_score.get(d, 0.0), reverse=True)
    # Within doc, order by start offset to preserve context
    for d in ordered_docs:
        by_doc[d].sort(key=lambda x: (x.get("metadata", {}).get("start", 0)))
    out: List[str] = []
    citations: List[Dict] = []
    total = 0
    cite_index = 1
    for did in ordered_docs:
        parts = by_doc[did]
        for it in parts:
            text = (it.get("content", "") or "").strip()
            if not text:
                continue
            # add citation marker if enabled
            suffix = ""
            if include_citations:
                suffix = f" [{cite_index}]"
            need = len(text) + (len(suffix) if suffix else 0)
            if total + need > max_chars:
                remain = max_chars - total
                if remain <= 0:
                    break
                clipped = text[: max(0, remain - len(suffix))]
                if clipped:
                    out.append(clipped + suffix)
                    total += len(clipped) + len(suffix)
                    if include_citations:
                        m = it.get("metadata", {})
                        citations.append({
                            "index": cite_index,
                            "source_path": m.get("source_path"),
                            "doc_id": m.get("doc_id"),
                            "start": m.get("start"),
                            "end": m.get("end"),
                            "heading_path": m.get("heading_path"),
                        })
                        cite_index += 1
                break
            out.append(text + suffix)
            total += need
            if include_citations:
                m = it.get("metadata", {})
                citations.append({
                    "index": cite_index,
                    "source_path": m.get("source_path"),
                    "doc_id": m.get("doc_id"),
                    "start": m.get("start"),
                    "end": m.get("end"),
                    "heading_path": m.get("heading_path"),
                })
                cite_index += 1
        if total >= max_chars:
            break
    merged = "\n\n".join(out)
    if include_citations and citations:
        lines: List[str] = [merged, "", "References:"]
        for c in citations:
            loc = ""
            if c.get("start") is not None and c.get("end") is not None:
                loc = f" ({c['start']}-{c['end']})"
            hp = f" – {c['heading_path']}" if c.get("heading_path") else ""
            sp = c.get("source_path") or c.get("doc_id") or "source"
            lines.append(f"[{c['index']}] {sp}{loc}{hp}")
        return "\n".join(lines)
    return merged


def compress_ranked_items(ranked_items: List[Dict], enable_compression: bool = True, max_per_doc: int = 2, join_gap: int = 200) -> List[Dict]:
    """
    【阶段 5 压缩】合并同文档的邻近片段，减少碎片。
    - 若当前片段与同文档上一片段的 start-end 间距 ≤ join_gap，则合并为一段
    - 否则作为新片段加入，但每文档最多保留 max_per_doc 个片段
    - 合并时取较高分，content 用 \\n\\n 拼接
    """
    if not enable_compression:
        return ranked_items
    by_doc_count: Dict[str, int] = {}
    last_by_doc: Dict[str, Dict] = {}
    new_items: List[Dict] = []
    for it in ranked_items:
        meta = it.get("metadata", {})
        did = meta.get("doc_id") or meta.get("source_path") or "unknown"
        start = int(meta.get("start") or 0)
        end = int(meta.get("end") or (start + len(it.get("content", "") or "")))
        if did not in last_by_doc:
            last_by_doc[did] = it
            by_doc_count[did] = 1
            new_items.append(it)
            continue
        last = last_by_doc[did]
        lmeta = last.get("metadata", {})
        lstart = int(lmeta.get("start") or 0)
        lend = int(lmeta.get("end") or (lstart + len(last.get("content", "") or "")))
        if start - lend <= join_gap and start >= lstart:
            # merge into last
            merged_text = (last.get("content", "") or "").strip()
            add_text = (it.get("content", "") or "").strip()
            if add_text:
                if merged_text:
                    merged_text = merged_text + "\n\n" + add_text
                else:
                    merged_text = add_text
                last["content"] = merged_text
                lmeta["end"] = max(lend, end)
                # keep the higher score
                try:
                    last["score"] = max(float(last.get("score", 0.0)), float(it.get("score", 0.0)))
                except Exception:
                    pass
            last_by_doc[did] = last
        else:
            cnt = by_doc_count.get(did, 0)
            if cnt >= max_per_doc:
                continue
            new_items.append(it)
            last_by_doc[did] = it
            by_doc_count[did] = cnt + 1
    return new_items


def tldr_summarize(text: str, bullets: int = 3) -> Optional[str]:
    """【阶段 5 TLDR】用 LLM 把检索片段总结成 3-5 条要点，用于快速预览。"""
    try:
        if not text or len(text.strip()) == 0:
            return None
        from ...core.llm import HelloAgentsLLM
        llm = HelloAgentsLLM()
        prompt = [
            {"role": "system", "content": "请将以下内容概括为简洁的要点列表（最多3-5条），用中文，避免重复，突出关键信息。"},
            {"role": "user", "content": f"请用 {max(1, min(5, int(bullets)))} 条要点总结：\n\n{text}"},
        ]
        out = llm.invoke(prompt)
        return out
    except Exception:
        return None


# ==================
# High-level RAG Pipeline API
# ==================

def create_rag_pipeline(
    qdrant_url: Optional[str] = None,
    qdrant_api_key: Optional[str] = None,
    collection_name: str = "hello_agents_rag_vectors",
    rag_namespace: str = "default"
) -> Dict[str, Any]:
    """
    【高层封装】创建完整的 RAG pipeline 实例，返回包含 store 和便捷方法的字典。

    用法：
        pipe = create_rag_pipeline(rag_namespace="docs")
        pipe["add_documents"](["a.pdf", "b.md"])
        hits = pipe["search"]("如何配置?", top_k=5)
        hits2 = pipe["search_advanced"]("如何配置?", enable_hyde=True)

    返回字典字段：
        - store: QdrantVectorStore 实例
        - namespace: 命名空间（隔离不同文档集）
        - add_documents(paths, chunk_size, chunk_overlap): 加载+分块+入库
        - search(query, top_k, score_threshold): 基础检索
        - search_advanced(query, ...): 扩展检索（MQE / HyDe）
        - get_stats(): collection 统计信息
    """
    dimension = get_dimension(1024)
    
    store = QdrantVectorStore(
        url=qdrant_url,
        api_key=qdrant_api_key,
        collection_name=collection_name,
        vector_size=dimension,
        distance="cosine"
    )
    
    def add_documents(file_paths: List[str], chunk_size: int = 800, chunk_overlap: int = 100):
        """Add documents to RAG pipeline"""
        chunks = load_and_chunk_texts(
            paths=file_paths,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            namespace=rag_namespace,
            source_label="rag"
        )
        index_chunks(
            store=store,
            chunks=chunks,
            rag_namespace=rag_namespace
        )
        return len(chunks)
    
    def search(query: str, top_k: int = 8, score_threshold: Optional[float] = None):
        """Search RAG knowledge base"""
        return search_vectors(
            store=store,
            query=query,
            top_k=top_k,
            rag_namespace=rag_namespace,
            score_threshold=score_threshold
        )
    
    def search_advanced(
        query: str, 
        top_k: int = 8, 
        enable_mqe: bool = False,
        enable_hyde: bool = False,
        score_threshold: Optional[float] = None
    ):
        """Advanced search with query expansion"""
        return search_vectors_expanded(
            store=store,
            query=query,
            top_k=top_k,
            rag_namespace=rag_namespace,
            enable_mqe=enable_mqe,
            enable_hyde=enable_hyde,
            score_threshold=score_threshold
        )
    
    def get_stats():
        """Get pipeline statistics"""
        return store.get_collection_stats()
    
    return {
        "store": store,
        "namespace": rag_namespace,
        "add_documents": add_documents,
        "search": search,
        "search_advanced": search_advanced,
        "get_stats": get_stats
    }