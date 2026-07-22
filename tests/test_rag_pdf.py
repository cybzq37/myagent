from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime
from typing import Dict, Any

from myagent import SimpleAgent, AgentLLM, ToolRegistry
from myagent.tools import RAGTool, MemoryTool

# 创建具有RAG能力的Agent
llm = AgentLLM()
agent = SimpleAgent(name="知识助手", llm=llm)


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
            "concepts_learned": 0
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

            # 【MemoryTool】记录到学习记忆
            self.memory_tool.run({
                "action": "add",
                "content": f"加载了文档《{self.current_document}》",
                "memory_type": "episodic",
                "importance": 0.9
            })

            return {
                "success": True,
                "message": f"加载成功！(耗时: {process_time:.1f}秒)",
                "document": self.current_document
            }
        else:
            return {
                "success": False,
                "message": f"加载失败: {result}"
            }


# === 测试执行 ===
if __name__ == "__main__":
    assistant = PDFLearningAssistant(user_id="test_user")
    print(f"会话ID: {assistant.session_id}")

    # 测试加载一个PDF（如果有的话）
    test_pdf = "./knowledge_base/Happy-LLM-0727.pdf"
    if os.path.exists(test_pdf):
        print(f"\n=== 加载PDF: {test_pdf} ===")
        result = assistant.load_document(test_pdf)
        print(f"结果: {result}")
    else:
        print(f"\n跳过PDF加载测试（文件不存在: {test_pdf}）")
        print("如需测试，请放置一个PDF文件到 ./knowledge_base/Happy-LLM-0727.pdf")

    print(f"\n=== 学习统计 ===")
    for k, v in assistant.stats.items():
        print(f"  {k}: {v}")
