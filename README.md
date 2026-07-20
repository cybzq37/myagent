# myagent

一个实验性质的 agent 框架。

## 环境要求

- Python >= 3.10
- [Poetry](https://python-poetry.org/) （依赖管理与打包）
- 一个可用的 LLM 服务（OpenAI 兼容接口 / Anthropic / Gemini 等）

## 安装

### 1. 克隆并安装依赖

```bash
git clone <repo-url>
cd myagent

# 安装核心依赖
poetry install

# 如需可选依赖，按 extra 安装：
poetry install --extras "gemini anthropic memory"
```

可选 extras 说明：

| extra | 安装内容 | 何时需要 |
|-------|---------|---------|
| `gemini` | `google-genai` | 使用 Google Gemini 作为 LLM |
| `anthropic` | `anthropic` | 使用 Anthropic Claude 作为 LLM |
| `memory` | `spacy` | 启用语义记忆模块（需要额外下载模型，见下） |

### 2. 配置环境变量

复制示例配置并填入你的 API 信息：

```bash
cp .env.example .env
```

编辑 `.env`，最少需要配置以下几项：

```env
# LLM 配置（必填）
LLM_MODEL_ID=your-model-name
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-llm-endpoint

# 超时时间（秒，可选，默认 60）
LLM_TIMEOUT=60

# 接口格式（可选）
# - chat_completions（默认）：走 /chat/completions，兼容 OpenAI 及绝大多数网关
# - responses：走 /responses，适用于只支持 Responses API 的网关
LLM_API_FORMAT=chat_completions
```

其它可选项（搜索 / 向量库 / 图数据库 / 嵌入等）见 `.env.example`，按需启用。

### 3. （可选）下载 spaCy 模型

仅当安装了 `memory` extra 并希望使用语义记忆功能时需要。框架会在模型缺失时自动降级，不会报错，但实体提取能力会受限。

```bash
# 中文模型（推荐）
python -m spacy download zh_core_web_sm

# 英文模型（可选）
python -m spacy download en_core_web_sm
```

> 说明：spaCy 模型是独立的发布包，不能通过 `pyproject.toml` 声明依赖自动安装，必须用 `spacy download` 命令下载。

## 运行测试

```bash
poetry run python tests/test_simple_agent.py
```

## 项目结构

```
myagent/
├── src/myagent/
│   ├── agents/        # 各类 Agent 实现（Simple / ReAct / Reflection / Plan-Solve）
│   ├── core/          # 基础设施：Agent 基类、LLM 适配器、消息、配置、生命周期
│   ├── context/       # 上下文工程：历史管理、截断、Token 计数
│   ├── tools/         # 工具系统：注册表、内建工具、工具过滤、熔断
│   ├── skills/        # 知识外化：SKILL.md 按需加载
│   ├── memory/        # 记忆系统：语义记忆（spaCy）
│   └── observability/ # 可观测性：TraceLogger（JSONL + HTML）
├── tests/
├── pyproject.toml
└── .env.example
```

## 常见问题

### 调用 LLM 一直没反应 / 503

- 检查 `LLM_BASE_URL` 是否需要加 `/v1` 后缀
- 检查 `LLM_API_FORMAT` 是否匹配你的网关：
  - 网关只支持 `/chat/completions` → `chat_completions`（默认）
  - 网关只支持 `/responses` → `responses`
- 设置较短的 `LLM_TIMEOUT`（如 30）便于快速失败定位问题

### `ModuleNotFoundError: No module named 'spacy'`

未安装 `memory` extra。如需语义记忆：

```bash
poetry install --extras "memory"
python -m spacy download zh_core_web_sm
```
