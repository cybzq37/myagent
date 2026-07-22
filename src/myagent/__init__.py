"""
MyAgent - 灵活、可扩展的多智能体框架

基于OpenAI原生API构建，提供简洁高效的智能体开发体验。
"""

import os
from pathlib import Path

# 加载 .env（如果存在），把配置写入环境变量
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parents[2] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# 配置 ffmpeg 路径（pydub/markitdown 音频处理用）
# 优先从 .env 读取 FFMPEG_PATH，把其所在目录加入 PATH，让 pydub 的 which() 能找到
_ffmpeg_path = os.getenv("FFMPEG_PATH")
if _ffmpeg_path and os.path.exists(_ffmpeg_path):
    _ffmpeg_dir = os.path.dirname(_ffmpeg_path)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    try:
        from pydub import AudioSegment
        AudioSegment.converter = _ffmpeg_path
    except ImportError:
        pass  # pydub 未安装则跳过

# 配置第三方库的日志级别，减少噪音
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

# 核心组件
from .core.llm import AgentLLM
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
    "AgentLLM",
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
