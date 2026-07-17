"""配置管理"""

import os
from typing import Optional, Dict, Any
from pydantic import BaseModel, model_validator

class Config(BaseModel):
    """MyAgent配置类

    集中管理框架所有可配置项，分为以下几组：
    - LLM 基础配置
    - 系统配置
    - 历史管理（向后兼容）
    - 上下文工程（窗口/压缩/摘要）
    - 工具输出截断
    - 可观测性（Trace）
    - Skills 知识外化
    - 熔断器
    - 会话持久化
    - 子代理机制
    - TodoWrite / DevLog
    - 异步生命周期
    - 流式输出
    """

    # ============ LLM 基础配置 ============
    default_model: str = "gpt-3.5-turbo"  # 默认模型名称，会被 .env 的 LLM_MODEL_ID 覆盖
    default_provider: str = "openai"  # LLM 提供商：openai / anthropic / gemini
    temperature: float = 0.7  # 采样温度，越高越随机，越低越确定
    max_tokens: Optional[int] = None  # 单次生成最大 Token 数，None 表示由模型决定

    # ============ 系统配置 ============
    debug: bool = False  # 是否开启调试模式（输出更多日志）
    log_level: str = "INFO"  # 日志级别：DEBUG / INFO / WARNING / ERROR

    # ============ 历史管理配置（向后兼容） ============
    max_history_length: int = 100  # 历史消息最大保留条数（旧字段，新逻辑由 HistoryManager 管理）

    # ============ 上下文工程配置 ============
    context_window: int = 128000  # 上下文窗口大小（Token 数），超过该值 * compression_threshold 触发压缩
    compression_threshold: float = 0.8  # 压缩阈值（0.8 = 占用 80% 窗口时触发历史压缩）
    min_retain_rounds: int = 10  # 压缩时至少保留最近 N 轮完整对话，不参与摘要
    enable_smart_compression: bool = False  # 是否启用智能摘要（调用轻量 LLM 生成结构化摘要，需额外 API 调用）

    # ============ 智能摘要配置（enable_smart_compression=True 时生效） ============
    summary_llm_provider: str = "deepseek"  # 摘要专用 LLM 提供商（建议用便宜模型降低成本）
    summary_llm_model: str = "deepseek-chat"  # 摘要专用 LLM 模型名称
    summary_max_tokens: int = 800  # 摘要最大 Token 数（控制摘要长度）
    summary_temperature: float = 0.3  # 摘要生成温度（偏低，保证摘要确定性和稳定性）

    # ============ 工具输出截断配置 ============
    tool_output_max_lines: int = 2000  # 工具输出保留的最大行数，超出则截断
    tool_output_max_bytes: int = 51200  # 工具输出保留的最大字节数（50KB）
    tool_output_dir: str = "tool-output"  # 完整输出（截断前的原始内容）的落盘目录
    tool_output_truncate_direction: str = "head"  # 截断方向：head 保留开头 / tail 保留结尾 / head_tail 两端各留一部分

    # ============ 可观测性配置 ============
    trace_enabled: bool = True  # 是否启用 Trace 记录（JSONL + HTML 双格式）
    trace_dir: str = "memory/traces"  # Trace 文件保存目录
    trace_sanitize: bool = True  # 是否对 Trace 中的敏感信息（API Key、路径）脱敏
    trace_html_include_raw_response: bool = False  # HTML 报告是否包含原始 LLM 响应（可能很长）

    # ============ Skills 知识外化配置 ============
    skills_enabled: bool = True  # 是否启用 Skills 渐进式披露系统
    skills_dir: str = "skills"  # Skills 目录路径（存放 SKILL.md 文件）
    skills_auto_register: bool = True  # 是否自动注册 SkillTool 到工具注册表

    # ============ 熔断器配置 ============
    circuit_enabled: bool = True  # 是否启用工具熔断器（连续失败自动禁用工具）
    circuit_failure_threshold: int = 3  # 连续失败多少次后熔断该工具
    circuit_recovery_timeout: int = 300  # 熔断后多少秒自动尝试恢复（半开状态）

    # ============ 会话持久化配置 ============
    session_enabled: bool = True  # 是否启用会话持久化（支持中断后恢复）
    session_dir: str = "memory/sessions"  # 会话文件保存目录
    auto_save_enabled: bool = False  # 是否启用自动保存（默认关闭，需手动调用 save）
    auto_save_interval: int = 10  # 自动保存间隔（每 N 条消息触发一次保存）

    # ============ 子代理机制配置 ============
    subagent_enabled: bool = True  # 是否启用子代理机制（TaskTool 派生子 Agent 执行子任务）
    subagent_max_steps: int = 15  # 子代理默认最大推理步数
    subagent_use_light_llm: bool = False  # 子代理是否使用轻量模型（降低成本，默认关闭以保持行为一致）
    subagent_light_llm_provider: str = "deepseek"  # 轻量模型提供商
    subagent_light_llm_model: str = "deepseek-chat"  # 轻量模型名称

    # ============ TodoWrite 进度管理配置 ============
    todowrite_enabled: bool = True  # 是否启用 TodoWrite 工具（任务列表与进度跟踪）
    todowrite_persistence_dir: str = "memory/todos"  # 任务列表持久化目录（跨会话保留）

    # ============ DevLog 开发日志配置 ============
    devlog_enabled: bool = True  # 是否启用 DevLog 工具（决策与开发日志记录）
    devlog_persistence_dir: str = "memory/devlogs"  # 开发日志持久化目录

    # ============ 异步生命周期配置 ============
    async_enabled: bool = True  # 是否启用异步执行（arun / arun_stream）
    max_concurrent_tools: int = 3  # 单轮最大并发工具调用数（并行优化）
    hook_timeout_seconds: float = 5.0  # 生命周期钩子（on_start/on_step 等）的超时时间（秒）
    llm_async_timeout: int = 120  # LLM 异步调用的超时时间（秒）
    tool_async_timeout: int = 30  # 工具异步调用的超时时间（秒）

    # ============ 流式输出配置 ============
    stream_enabled: bool = True  # 是否启用流式输出（打字机效果）
    stream_buffer_size: int = 100  # 流式缓冲区大小（Token / 字符数）
    stream_include_thinking: bool = True  # 流式输出是否包含思考过程（o1 / deepseek-reasoner 的推理链）
    stream_include_tool_calls: bool = True  # 流式输出是否包含工具调用事件

    @staticmethod
    def _get_env_bool(name: str) -> Optional[bool]:
        value = os.getenv(name)
        if value is None:
            return None
        value = value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return None

    @staticmethod
    def _get_env_int(name: str) -> Optional[int]:
        value = os.getenv(name)
        if value is None or not value.strip():
            return None
        return int(value)

    @staticmethod
    def _get_env_float(name: str) -> Optional[float]:
        value = os.getenv(name)
        if value is None or not value.strip():
            return None
        return float(value)

    @staticmethod
    def _get_env_str(name: str) -> Optional[str]:
        value = os.getenv(name)
        if value is None or not value.strip():
            return None
        return value

    @classmethod
    def _env_defaults(cls) -> Dict[str, Any]:
        defaults: Dict[str, Any] = {}

        mappings = {
            "debug": cls._get_env_bool("DEBUG"),
            "log_level": cls._get_env_str("LOG_LEVEL"),
            "temperature": cls._get_env_float("TEMPERATURE"),
            "max_tokens": cls._get_env_int("MAX_TOKENS"),
            "trace_enabled": cls._get_env_bool("TRACE_ENABLED"),
            "trace_dir": cls._get_env_str("TRACE_DIR"),
            "trace_sanitize": cls._get_env_bool("TRACE_SANITIZE"),
            "trace_html_include_raw_response": cls._get_env_bool("TRACE_HTML_INCLUDE_RAW_RESPONSE"),
        }

        for key, value in mappings.items():
            if value is not None:
                defaults[key] = value

        return defaults

    @model_validator(mode="before")
    @classmethod
    def apply_env_defaults(cls, data: Any) -> Any:
        """为未显式传入的字段填充环境变量默认值。"""
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return data

        merged = cls._env_defaults()
        merged.update(data)
        return merged

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量创建配置

        支持的环境变量：
        - DEBUG: 是否开启调试模式（"true"/"false"）
        - LOG_LEVEL: 日志级别
        - TEMPERATURE: 采样温度
        - MAX_TOKENS: 最大生成 Token 数
        - TRACE_ENABLED: 是否启用 Trace
        - TRACE_DIR: Trace 输出目录
        - TRACE_SANITIZE: 是否脱敏
        - TRACE_HTML_INCLUDE_RAW_RESPONSE: HTML 是否包含原始响应
        """
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化和日志输出）"""
        return self.model_dump()
