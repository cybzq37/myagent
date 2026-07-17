# MyAgent 源码架构文档

> 版本：1.0.0 · 作者：MyAgent Team (jjyaoao@126.com)
> 基于 Datawhale Hello-Agents 教程的灵活、可扩展多智能体框架

---

## 项目概览

**MyAgent** 是一个基于 OpenAI 原生 API 构建的多智能体框架，核心理念：

- **统一 LLM 接口**：一套 API 调用 OpenAI / Anthropic / Gemini 及所有兼容服务
- **多种 Agent 范式**：Simple / ReAct / Reflection / PlanSolve，全部基于 Function Calling
- **上下文工程**：GSSC 流水线 + 历史压缩 + 输出截断 + Token 计数
- **可观测性**：JSONL + HTML 双格式 Trace
- **知识外化**：Skills 渐进式披露，无需 fine-tuning
- **子代理机制**：TaskTool + ToolFilter + 工厂函数

---

## 目录结构总览

```
src/
├── __init__.py          # 框架入口，导出公共 API
├── version.py           # 版本信息
├── core/                # 核心抽象层
│   ├── __init__.py
│   ├── agent.py         # Agent 抽象基类
│   ├── llm.py           # 统一 LLM 客户端
│   ├── llm_adapters.py  # LLM 适配器（OpenAI/Anthropic/Gemini）
│   ├── llm_response.py  # 统一响应对象
│   ├── config.py        # 配置类（Pydantic）
│   ├── message.py       # 消息类
│   ├── exceptions.py    # 异常体系
│   ├── lifecycle.py     # 异步生命周期事件系统
│   ├── streaming.py     # SSE 流式输出
│   └── session_store.py # 会话持久化
├── agents/              # Agent 范式实现
│   ├── __init__.py
│   ├── factory.py       # Agent 工厂函数
│   ├── simple_agent.py  # 简单对话 Agent
│   ├── react_agent.py   # ReAct 推理-行动 Agent
│   ├── reflection_agent.py  # 反思型 Agent
│   └── plan_solve_agent.py  # 规划-执行 Agent
├── tools/               # 工具系统
│   ├── __init__.py
│   ├── base.py          # 工具基类 + @tool_action 装饰器
│   ├── registry.py      # 工具注册表
│   ├── response.py      # 工具响应协议
│   ├── errors.py        # 工具错误码
│   ├── circuit_breaker.py   # 熔断器
│   ├── tool_filter.py   # 工具过滤器（子代理权限）
│   └── builtin/         # 内置工具集合
│       ├── __init__.py
│       ├── calculator.py    # 数学计算
│       ├── file_tools.py    # 文件读写编辑（乐观锁）
│       ├── todowrite_tool.py  # 任务列表管理
│       ├── devlog_tool.py   # 开发日志
│       ├── task_tool.py     # 子代理工具
│       └── skill_tool.py    # 技能加载工具
├── context/             # 上下文工程
│   ├── __init__.py
│   ├── builder.py       # GSSC 流水线
│   ├── history.py       # 历史管理器
│   ├── truncator.py     # 工具输出截断器
│   └── token_counter.py # Token 计数器
├── observability/       # 可观测性
│   ├── __init__.py
│   └── trace_logger.py  # 双格式 Trace 记录器
└── skills/              # 知识外化
    ├── __init__.py
    └── loader.py        # Skills 加载器（渐进式披露）
```

---

## 各模块详解

### 1. `core/` — 核心抽象层

框架的基石，定义所有 Agent 共享的抽象与基础设施。

#### [agent.py](../src/core/agent.py) — Agent 抽象基类

集成能力：
- **HistoryManager**：历史管理与压缩
- **ObservationTruncator**：工具输出截断
- **TraceLogger**：可观测性（JSONL + HTML）
- **ToolRegistry**：工具管理（可选）
- **SkillLoader**：知识外化（可选）
- **SessionStore**：会话持久化
- **子代理机制**：TaskTool 自动注册
- **TodoWrite / DevLog**：进度管理与决策记录

执行入口：
- `run()` — 同步执行
- `arun()` — 异步执行（支持生命周期钩子 on_start/on_step/on_finish/on_error）
- `arun_stream()` — 异步流式执行（返回 AgentEvent 生成器）

历史压缩策略：
- 简单摘要：统计信息（轮次、消息数）
- 智能摘要：调用轻量 LLM 生成结构化摘要（任务目标/关键决策/已完成/待处理/重要发现）

向后兼容：`self._history` 通过 property 代理到 HistoryManager。

#### [llm.py](../src/core/llm.py) — 统一 LLM 客户端 `MyAgent`

- 根据 base_url 自动选择适配器
- 支持 OpenAI 兼容接口、Anthropic Claude、Google Gemini
- 自动识别 Thinking Model（o1、deepseek-reasoner）
- 统一配置：`LLM_MODEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_TIMEOUT`
- 方法：`invoke` / `stream_invoke` / `astream_invoke` / `invoke_with_tools`

#### [llm_adapters.py](../src/core/llm_adapters.py) — LLM 适配器层

`BaseLLMAdapter` 抽象基类，屏蔽不同厂商接口差异：
- OpenAI 适配器（兼容 DeepSeek/Qwen/Kimi/智谱/Ollama）
- Anthropic 适配器
- Gemini 适配器

#### [llm_response.py](../src/core/llm_response.py) — 统一响应对象

- `LLMResponse`：普通响应（content / model / usage / latency_ms）
- `LLMToolResponse`：工具调用响应（content / tool_calls / model / usage）
- `ToolCall`：统一工具调用对象（id / name / arguments）
- `StreamStats`：流式调用统计

#### [config.py](../src/core/config.py) — 配置类 `Config`（Pydantic BaseModel）

配置分组：
| 分组 | 关键字段 |
|---|---|
| LLM | `default_model` / `temperature` / `max_tokens` |
| 上下文工程 | `context_window=128000` / `compression_threshold=0.8` / `min_retain_rounds=10` |
| 智能摘要 | `summary_llm_provider="deepseek"` / `summary_max_tokens=800` |
| 工具输出截断 | `tool_output_max_lines=2000` / `tool_output_max_bytes=51200` |
| 可观测性 | `trace_enabled=True` / `trace_dir="memory/traces"` |
| Skills | `skills_enabled=True` / `skills_auto_register=True` |
| 熔断器 | `circuit_failure_threshold=3` / `circuit_recovery_timeout=300` |
| 会话持久化 | `session_enabled=True` / `auto_save_interval=10` |
| 子代理 | `subagent_enabled=True` / `subagent_max_steps=15` |
| TodoWrite | `todowrite_enabled=True` / `todowrite_persistence_dir` |
| DevLog | `devlog_enabled=True` / `devlog_persistence_dir` |
| 异步 | `async_enabled=True` / `max_concurrent_tools=3` / `hook_timeout_seconds=5.0` |
| 流式 | `stream_enabled=True` / `stream_include_thinking=True` |

#### [message.py](../src/core/message.py) — 消息类 `Message`

支持五种角色：`user` / `assistant` / `system` / `tool` / `summary`

方法：`to_dict()` / `from_dict()` / `to_text()`

#### [exceptions.py](../src/core/exceptions.py) — 异常体系

```
MyAgentException
├── LLMException
├── AgentException
├── ConfigException
└── ToolException
```

#### [lifecycle.py](../src/core/lifecycle.py) — 异步生命周期事件系统

`EventType` 枚举：
- Agent 级：`AGENT_START` / `AGENT_FINISH` / `AGENT_ERROR`
- 步骤级：`STEP_START` / `STEP_FINISH`
- LLM 级：`LLM_START` / `LLM_CHUNK` / `LLM_FINISH`
- 工具级：`TOOL_CALL` / `TOOL_RESULT` / `TOOL_ERROR`
- 特殊：`THINKING` / `REFLECTION` / `PLAN`

支持生命周期钩子 `LifecycleHook`，事件驱动执行流程。

#### [streaming.py](../src/core/streaming.py) — SSE 流式输出

`StreamEvent` + `StreamEventType`，适配 WebSocket/SSE 场景的实时事件推送。

#### [session_store.py](../src/core/session_store.py) — 会话持久化 `SessionStore`

- JSON 文件原子写入
- 会话恢复
- 环境一致性检查
- 会话列表管理

---

### 2. `agents/` — Agent 范式实现

#### [simple_agent.py](../src/agents/simple_agent.py) — SimpleAgent

基于 Function Calling 的对话 Agent：
- 纯对话模式（无工具）
- 多轮工具调用循环（`max_tool_iterations=3`）
- `stream_run()` 同步流式 / `arun_stream()` 异步流式

#### [react_agent.py](../src/agents/react_agent.py) — ReActAgent

基于 Function Calling 的推理-行动循环：
- 内置 **Thought 工具**（显式推理，参数 reasoning）
- 内置 **Finish 工具**（结束流程，参数 answer）
- 无需正则解析，成功率 99%+
- `max_steps=5` 控制最大步数

#### [reflection_agent.py](../src/agents/reflection_agent.py) — ReflectionAgent

自我反思与迭代优化：
- 内置 `Memory` 模块记录执行与反思轨迹
- 执行 → 反思 → 优化 → 迭代
- 适合代码生成、文档写作、分析报告

#### [plan_solve_agent.py](../src/agents/plan_solve_agent.py) — PlanSolveAgent

先规划后执行：
- `Planner`：用 Function Calling 生成分步计划
- `Executor`：逐步执行并维护历史
- 最后一步的响应作为最终答案

#### [factory.py](../src/agents/factory.py) — 工厂函数

- `create_agent(agent_type, name, llm, ...)`：统一创建四种 Agent
  - `"react"` / `"reflection"` / `"plan"` / `"simple"`
- `default_subagent_factory(...)`：为子代理机制提供默认实现，按类型分配系统提示词

---

### 3. `tools/` — 工具系统

#### [base.py](../src/tools/base.py) — 工具基类

- `Tool`：抽象基类
- `ToolParameter`：参数定义（name / type / description / required / default）
- `@tool_action(name, description)`：装饰器，标记方法为可展开的工具 action
- 支持可展开工具（一个 Tool 展开为多个子工具）

#### [registry.py](../src/tools/registry.py) — 工具注册表 `ToolRegistry`

- 两种注册方式：Tool 对象（推荐）/ 函数直接注册（简便）
- 集成熔断器
- 文件元数据缓存（乐观锁机制）
- `global_registry`：全局单例

#### [response.py](../src/tools/response.py) — 工具响应协议 `ToolResponse`

标准化字段：
- `status`：SUCCESS / PARTIAL / ERROR
- `text`：给 LLM 阅读的格式化文本
- `data`：结构化数据载荷
- `error_info`：错误信息
- `stats`：运行统计
- `context`：上下文信息

#### [circuit_breaker.py](../src/tools/circuit_breaker.py) — 熔断器 `CircuitBreaker`

状态机：`Closed (正常) → Open (熔断) → Closed (恢复)`
- 连续失败 N 次自动熔断（默认 3）
- 超时自动恢复（默认 300 秒）
- 基于 ToolResponse 协议判断错误

#### [tool_filter.py](../src/tools/tool_filter.py) — 工具过滤器

用于子代理机制，控制不同 Agent 可访问的工具集：
- `ReadOnlyFilter`：只读权限
- `FullAccessFilter`：完全权限
- `CustomFilter`：自定义权限

#### 内置工具 `builtin/`

| 文件 | 工具 | 功能 |
|---|---|---|
| [calculator.py](../src/tools/builtin/calculator.py) | `CalculatorTool` | 数学计算 |
| [file_tools.py](../src/tools/builtin/file_tools.py) | `ReadTool` / `WriteTool` / `EditTool` / `MultiEditTool` | 文件读写编辑（支持乐观锁） |
| [todowrite_tool.py](../src/tools/builtin/todowrite_tool.py) | `TodoWriteTool` | 任务列表管理（进度跟踪，持久化到 `memory/todos`） |
| [devlog_tool.py](../src/tools/builtin/devlog_tool.py) | `DevLogTool` | 开发日志（决策记录，持久化到 `memory/devlogs`） |
| [task_tool.py](../src/tools/builtin/task_tool.py) | `TaskTool` | 子代理工具（派生子 Agent 执行子任务） |
| [skill_tool.py](../src/tools/builtin/skill_tool.py) | `SkillTool` | 技能加载工具（按需加载 SKILL.md 知识） |

---

### 4. `context/` — 上下文工程

#### [builder.py](../src/context/builder.py) — ContextBuilder（GSSC 流水线）

四阶段上下文构建：
1. **Gather**：从多源收集候选信息（历史、工具结果）
2. **Select**：基于优先级、相关性、多样性筛选
3. **Structure**：组织成结构化上下文模板
4. **Compress**：在 Token 预算内压缩与规范化

数据结构：`ContextPacket`（content / timestamp / metadata / token_count / relevance_score）

#### [history.py](../src/context/history.py) — HistoryManager

- 只追加不编辑（缓存友好）
- 自动压缩：summary + 保留最近 N 轮完整对话
- 轮次边界检测
- 序列化 / 反序列化

#### [truncator.py](../src/context/truncator.py) — ObservationTruncator

- 多方向截断：head / tail / head_tail
- 自动保存完整输出到文件
- 返回 `ToolResponse.partial()` 状态

#### [token_counter.py](../src/context/token_counter.py) — TokenCounter

- 本地预估（tiktoken，无需 API 调用）
- 缓存机制（避免重复计算）
- 增量计算（只计算新增消息）
- 降级方案（tiktoken 不可用时用字符估算）

---

### 5. `observability/` — 可观测性

#### [trace_logger.py](../src/observability/trace_logger.py) — TraceLogger

双格式 Trace 记录：
- **JSONL**：机器可读，流式追加，支持 jq 分析
- **HTML**：人类可读，可视化审计界面，内置统计面板（Token / 工具调用 / 错误）

特性：
- 自动脱敏（API Key、路径）
- 增量渲染（实时可查看）
- 事件类型：`session_start` / `message_written` / `model_output` / `tool_call` / `tool_result` / `error` / `session_end`

---

### 6. `skills/` — 知识外化

#### [loader.py](../src/skills/loader.py) — SkillLoader（渐进式披露）

三层加载机制：
| 层级 | 内容 | 时机 | Token 成本 |
|---|---|---|---|
| Layer 1 | Metadata（名称+描述） | 启动时加载 | ~100 tokens/skill |
| Layer 2 | SKILL.md body | 按需加载 | ~2000+ tokens |
| Layer 3 | Resources（scripts/examples） | 可选 | 按需 |

设计要点：
- 作为 `tool_result` 注入，不修改 system_prompt
- 人类可编辑（SKILL.md 文件，支持版本控制）
- 预期节省 85% Token（20 个 skills 场景）

`Skill` 数据类：`name` / `description` / `body` / `path` / `dir` / `scripts` / `examples`

---

## 架构亮点

1. **统一 LLM 抽象**：一套 API 调用 OpenAI/Anthropic/Gemini 及所有兼容服务（DeepSeek/Qwen/Kimi/智谱/Ollama）
2. **四种 Agent 范式**：Simple/ReAct/Reflection/PlanSolve，全部基于 Function Calling，无需正则解析
3. **上下文工程**：GSSC 流水线 + 历史压缩 + 输出截断 + Token 计数，系统化管理上下文窗口
4. **可观测性**：JSONL + HTML 双格式 Trace，支持脱敏与统计面板
5. **知识外化**：Skills 渐进式披露，避免 fine-tuning
6. **子代理机制**：TaskTool + ToolFilter + 工厂函数，支持任务分解与权限控制
7. **异步生命周期**：事件驱动 + 钩子机制 + 流式输出，适配 SSE/WebSocket 场景
8. **熔断器**：工具连续失败自动熔断，防止死循环
9. **会话持久化**：原子写入 + 环境一致性检查，支持会话恢复

---

## 快速上手

```python
from src import MyAgent, Config, create_agent
from src.tools.registry import ToolRegistry
from src.tools.builtin.calculator import CalculatorTool

# 1. 初始化 LLM（配置从 .env 读取）
llm = MyAgent()

# 2. 准备工具
registry = ToolRegistry()
registry.register_tool(CalculatorTool())

# 3. 创建 Agent
agent = create_agent(
    agent_type="react",
    name="my-agent",
    llm=llm,
    tool_registry=registry,
    config=Config(),
    system_prompt="你是一个高效的助手"
)

# 4. 运行
answer = agent.run("计算 123 * 456")
print(answer)
```

环境变量配置（`.env`）：

```
LLM_MODEL_ID=你的模型ID
LLM_API_KEY=你的API密钥
LLM_BASE_URL=你的服务地址
LLM_TIMEOUT=60
```
