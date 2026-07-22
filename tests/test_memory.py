from dotenv import load_dotenv
load_dotenv()

from myagent import SimpleAgent, AgentLLM, ToolRegistry
from myagent.tools import MemoryTool, RAGTool

# 创建LLM实例
llm = AgentLLM()

# 创建Agent
agent = SimpleAgent(
    name="智能助手",
    llm=llm,
    system_prompt="你是一个有记忆和知识检索能力的AI助手"
)

# 创建工具注册表
tool_registry = ToolRegistry()

# 添加记忆工具
memory_tool = MemoryTool(user_id="user123")
tool_registry.register_tool(memory_tool)

# 添加RAG工具
rag_tool = RAGTool(knowledge_base_path="./knowledge_base")
tool_registry.register_tool(rag_tool)

# 为Agent配置工具
agent.tool_registry = tool_registry

# 体验记忆功能
print("=== 添加多个记忆 ===")

# 添加第一个记忆
result1 = memory_tool.run({
    "action": "add",
    "content": "用户张三是一名Python开发者，专注于机器学习和数据分析",
    "memory_type": "semantic",
    "importance": 0.8
})
print(f"记忆1: {result1}")

# 添加第二个记忆
result2 = memory_tool.run({
    "action": "add",
    "content": "李四是前端工程师，擅长React和Vue.js开发",
    "memory_type": "semantic",
    "importance": 0.7
})
print(f"记忆2: {result2}")

# 添加第三个记忆
result3 = memory_tool.run({
    "action": "add",
    "content": "王五是产品经理，负责用户体验设计和需求分析",
    "memory_type": "semantic",
    "importance": 0.6
})
print(f"记忆3: {result3}")

print("\n=== 搜索特定记忆 ===")
# 搜索前端相关的记忆
print("🔍 搜索 '前端工程师':")
result = memory_tool.run({
    "action": "search",
    "query": "前端工程师",
    "limit": 3
})
print(result)

print("\n=== 记忆摘要 ===")
result = memory_tool.run({"action": "summary"})
print(result)
