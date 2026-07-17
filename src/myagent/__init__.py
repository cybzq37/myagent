"""
MyAgent - 灵活、可扩展的多智能体框架

基于OpenAI原生API构建，提供简洁高效的智能体开发体验。
"""

# 配置第三方库的日志级别，减少噪音
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

# 核心组件
from .core.llm import MyAgent
from .core.config import Config
from .core.message import Message
from .core.exceptions import MyAgentException

# Agent实现
from .agents.simple_agent import SimpleAgent
from .agents.react_agent import ReActAgent
from .agents.reflection_agent import ReflectionAgent
from .agents.plan_solve_agent import PlanSolveAgent

# 工具系统
from .tools.registry import ToolRegistry, global_registry
from .tools.builtin.calculator import CalculatorTool, calculate

__all__ = [

    # 核心组件
    "MyAgent",
    "Config",
    "Message",
    "MyAgentException",

    # Agent范式
    "SimpleAgent",
    "ReActAgent",
    "ReflectionAgent",
    "PlanSolveAgent",

    # 工具系统
    "ToolRegistry",
    "global_registry",
    "CalculatorTool",
    "calculate",
]

