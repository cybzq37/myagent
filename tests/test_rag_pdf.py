from dotenv import load_dotenv

load_dotenv()

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

from myagent.tools import RAGTool, MemoryTool


class PDFLearningAssistant:
    """智能文档问答助手"""

    def __init__(self, user_id: str = "default_user"):
        """初始化学习助手

        Args:
            user_id: 用户ID，用于隔离不同用户的数据
        """
        self.user_id = user_id
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 初始化工具
        self.memory_tool = MemoryTool(user_id=user_id)
        self.rag_tool = RAGTool(rag_namespace=f"pdf_{user_id}")

        # 学习统计
        self.stats = {
            "session_start": datetime.now(),
            "documents_loaded": 0,
            "questions_asked": 0,
            "concepts_learned": 0,
        }

        # 当前加载的文档
        self.current_document = None

    def load_document(self, pdf_path: str) -> Dict[str, Any]:
        """加载PDF文档到知识库

        Args:
            pdf_path: PDF文件路径

        Returns:
            Dict: 包含success和message的结果
        """
        if not os.path.exists(pdf_path):
            return {"success": False, "message": f"文件不存在: {pdf_path}"}

        start_time = datetime.now().timestamp()

        # 【RAGTool】处理PDF: MarkItDown转换 → 智能分块 → 向量化
        result = self.rag_tool.add_document(file_path=pdf_path)

        process_time = datetime.now().timestamp() - start_time

        # 工具返回的是字符串，判断是否包含成功标记
        if "[OK]" in result or "已添加" in result or "成功" in result:
            self.current_document = os.path.basename(pdf_path)
            self.stats["documents_loaded"] += 1

            # 【MemoryTool】记录到情景记忆
            self.memory_tool.run(
                {
                    "action": "add",
                    "content": f"加载了文档《{self.current_document}》",
                    "memory_type": "episodic",
                    "importance": 0.9,
                    "event_type": "document_loaded",
                    "session_id": self.session_id,
                }
            )

            return {
                "success": True,
                "message": f"加载成功！(耗时: {process_time:.1f}秒)",
                "document": self.current_document,
            }
        else:
            return {"success": False, "message": f"加载失败: {result}"}

    def ask(self, question: str, use_advanced_search: bool = True) -> str:
        """向文档提问

        Args:
            question: 用户问题
            use_advanced_search: 是否使用高级检索（MQE + HyDE）

        Returns:
            str: 答案
        """
        if not self.current_document:
            return "请先加载文档！"

        # 【MemoryTool】记录问题到工作记忆
        self.memory_tool.run(
            {
                "action": "add",
                "content": f"提问: {question}",
                "memory_type": "working",
                "importance": 0.6,
                "session_id": self.session_id
            }
        
        )

        # 【RAGTool】使用高级检索获取答案
        answer = self.rag_tool.run(
            {
                "action": "ask",
                "question": question,
                "limit": 5,
                "enable_advanced_search": use_advanced_search,
                "enable_mqe": use_advanced_search,
                "enable_hyde": use_advanced_search
            }
        )

        # 【MemoryTool】记录到情景记忆
        self.memory_tool.run(
            {
                "action": "add",
                "content": f"关于'{question}'的学习",
                "memory_type": "episodic",
                "importance": 0.7,
                "event_type": "qa_interaction",
                "session_id": self.session_id
            }
        )

        self.stats["questions_asked"] += 1

        return answer
    
    def add_note(self, content: str, concept: Optional[str] = None):
        """添加学习笔记"""
        self.memory_tool.run({
            "action": "add",
            "content": content,
            "memory_type": "semantic",
            "importance": 0.8,
        })
        self.stats["concepts_learned"] += 1

    def recall(self, query: str, limit: int = 5) -> str:
        """回顾学习历程"""
        result = self.memory_tool.run({
            "action": "search",
            "query": query,
            "limit": limit
        })
        return result

    def get_stats(self) -> Dict[str, Any]:
        """获取学习统计"""
        duration = (datetime.now() - self.stats["session_start"]).total_seconds()
        return {
            "会话时长": f"{duration:.0f}秒",
            "加载文档": self.stats["documents_loaded"],
            "提问次数": self.stats["questions_asked"],
            "学习笔记": self.stats["concepts_learned"],
            "当前文档": self.current_document or "未加载"
        }

    def generate_report(self, save_to_file: bool = True) -> Dict[str, Any]:
        """生成学习报告"""
        memory_summary = self.memory_tool.run({"action": "summary", "limit": 10})
        rag_stats = self.rag_tool.run({"action": "stats"})

        duration = (datetime.now() - self.stats["session_start"]).total_seconds()
        report = {
            "session_info": {
                "session_id": self.session_id,
                "user_id": self.user_id,
                "start_time": self.stats["session_start"].isoformat(),
                "duration_seconds": duration
            },
            "learning_metrics": {
                "documents_loaded": self.stats["documents_loaded"],
                "questions_asked": self.stats["questions_asked"],
                "concepts_learned": self.stats["concepts_learned"]
            },
            "memory_summary": memory_summary,
            "rag_status": rag_stats
        }

        if save_to_file:
            report_file = f"learning_report_{self.session_id}.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            report["report_file"] = report_file

        return report



# === 测试执行 ===
if __name__ == "__main__":
    import sys
    import signal

    assistant = PDFLearningAssistant(user_id="test_user")
    print(f"会话ID: {assistant.session_id}")

    # 加载 PDF
    test_pdf = "./knowledge_base/Happy-LLM-0727.pdf"
    if not os.path.exists(test_pdf):
        print(f"\n文件不存在: {test_pdf}")
        print("请放置一个PDF文件到该路径后再运行。")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"加载文档: {test_pdf}")
    print(f"{'='*50}")
    result = assistant.load_document(test_pdf)
    print(f"结果: {result}")

    # 多轮对话循环
    print(f"\n{'='*50}")
    print("进入问答模式，输入问题后回车即可得到回答。")
    print("按 Ctrl+C 退出。")
    print(f"{'='*50}\n")

    def signal_handler(sig, frame):
        print("\n\n正在退出...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    while True:
        try:
            question = input(">>> ").strip()
            if not question:
                continue
        except (EOFError, KeyboardInterrupt):
            print("\n\n正在退出...")
            break

        answer = assistant.ask(question)
        print(f"\n{answer}\n")

    print(f"\n=== 学习统计 ===")
    for k, v in assistant.stats.items():
        print(f"  {k}: {v}")

    # 显式关闭 Neo4j 连接，避免解释器关闭时触发 Bolt.__del__ 的 ImportError
    mm = assistant.memory_tool.memory_manager
    if "semantic" in mm.memory_types:
        semantic = mm.memory_types["semantic"]
        if hasattr(semantic, "graph_store") and semantic.graph_store:
            semantic.graph_store.close()
            print("\n[Cleanup] Neo4j 连接已安全关闭")
