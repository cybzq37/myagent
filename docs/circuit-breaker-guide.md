# 熔断器机制使用指�?

> 防止工具连续失败导致的死循环�?Token 浪费

---

##  什么是熔断器？

熔断器（Circuit Breaker）是一种保护机制，当工具连续失败达到阈值时，自动禁用该工具一段时间，避免�?

- **死循�?*：模型在坏工具上无限重试
- **Token 浪费**：每次失败消�?200+ tokens�?00 �?= 20K tokens
- **资源占用**：持续调用失败的外部 API
- **用户体验�?*：任务卡住，无法判断是问题还是正常等�?

---

##  核心特�?

### 1. 自动熔断

连续失败 3 次（默认）后，工具自动被禁用�?

```
调用 1 �?失败 �?(失败计数: 1)
调用 2 �?失败 �?(失败计数: 2)
调用 3 �?失败 �?(失败计数: 3)
 工具已熔�?
调用 4 �?返回 CIRCUIT_OPEN 错误（工具未被实际调用）
```

### 2. 自动恢复

熔断 5 分钟（默认）后，工具自动恢复可用�?

```
00:00 - 工具熔断
05:00 - 自动恢复
05:01 - 可以再次调用
```

### 3. 成功重置

任何一次成功调用会重置失败计数�?

```
调用 1 �?失败 �?(失败计数: 1)
调用 2 �?失败 �?(失败计数: 2)
调用 3 �?成功 �?(失败计数: 0)  # 重置
调用 4 �?失败 �?(失败计数: 1)  # 重新开始计�?
```

### 4. 独立管理

每个工具独立计数，互不影响：

```
tool_a: 失败 3 �?�?熔断 
tool_b: 正常运行 �?可用 
```

---

##  快速开�?

### 零配置使用（推荐�?

框架默认启用熔断器，无需任何配置�?

```python
from myagent import ToolRegistry, ReActAgent
from myagent.llm import OpenAILLM

# 创建 LLM
llm = OpenAILLM(model="gpt-4")

# 创建工具注册表（默认启用熔断器）
registry = ToolRegistry()

# 注册工具
registry.register_tool(your_tool)

# 创建 Agent
agent = ReActAgent("assistant", llm, tool_registry=registry)

# 运行（熔断器自动工作�?
result = agent.run("帮我完成任务")
```

**就这么简单！** 熔断器会自动�?
- 监控所有工具的执行结果
- 连续失败 3 次后熔断
- 5 分钟后自动恢�?

---

##  自定义配�?

### 方式 1：通过 Config 配置

```python
from myagent.core.config import Config
from myagent.tools.circuit_breaker import CircuitBreaker
from myagent import ToolRegistry

# 创建配置
config = Config(
    circuit_enabled=True,              # 启用熔断�?
    circuit_failure_threshold=5,       # 5 次失败后熔断（默�?3�?
    circuit_recovery_timeout=600       # 10 分钟后恢复（默认 300�?
)

# 创建熔断�?
cb = CircuitBreaker(
    failure_threshold=config.circuit_failure_threshold,
    recovery_timeout=config.circuit_recovery_timeout,
    enabled=config.circuit_enabled
)

# 创建工具注册�?
registry = ToolRegistry(circuit_breaker=cb)
```

### 方式 2：直接创建熔断器

```python
from myagent.tools.circuit_breaker import CircuitBreaker
from myagent import ToolRegistry

# 自定义熔断器
cb = CircuitBreaker(
    failure_threshold=10,    # 10 次失败后熔断
    recovery_timeout=1800,   # 30 分钟后恢�?
    enabled=True
)

registry = ToolRegistry(circuit_breaker=cb)
```

### 方式 3：禁用熔断器

```python
from myagent.tools.circuit_breaker import CircuitBreaker
from myagent import ToolRegistry

# 禁用熔断�?
cb = CircuitBreaker(enabled=False)
registry = ToolRegistry(circuit_breaker=cb)

# 或者通过 Config
from myagent.core.config import Config
config = Config(circuit_enabled=False)
```

---

##  手动控制

### 查看工具状�?

```python
# 查看单个工具状�?
status = registry.circuit_breaker.get_status("tool_name")
print(status)
# 输出�?
# {
#     'state': 'open',              # 'open' �?'closed'
#     'failure_count': 3,           # 失败次数
#     'open_since': 1738245123.45,  # 熔断开始时间（时间戳）
#     'recover_in_seconds': 245     # 恢复倒计时（秒）
# }

# 查看所有工具状�?
all_status = registry.circuit_breaker.get_all_status()
for tool_name, status in all_status.items():
    print(f"{tool_name}: {status['state']} (失败 {status['failure_count']} �?")
```

### 手动开�?关闭熔断

```python
# 手动熔断某个工具
registry.circuit_breaker.open("problematic_tool")
# 输出：�?Circuit Breaker: 工具 'problematic_tool' 已手动熔�?

# 手动恢复某个工具
registry.circuit_breaker.close("problematic_tool")
# 输出：�?Circuit Breaker: 工具 'problematic_tool' 已恢�?
```

---

##  实际案例

### 案例 1：MCP 服务器宕�?

**场景**：MCP 服务器宕机，工具调用失败

**之前**�?
```
00:00 - 调用 MCP 工具 �?失败（Connection refused�?
00:02 - 再次调用 �?失败
00:04 - 再次调用 �?失败
... 无限重试，浪费大�?Token
```

**之后**�?
```
00:00 - 调用 MCP 工具 �?失败（失败计�? 1�?
00:02 - 再次调用 �?失败（失败计�? 2�?
00:04 - 再次调用 �?失败（失败计�? 3�?
00:04 -  工具已熔�?
00:06 - 模型尝试调用 �?返回 CIRCUIT_OPEN 错误
00:06 - 模型跳过此工具，尝试其他方法 �?
05:04 - 自动恢复
```

**收益**：节�?97% Token�? �?vs 100 次）

### 案例 2：工具配置错�?

**场景**：工具配置了错误�?API endpoint

**之前**�?
```
每次调用失败，耗时 2-3 �?
100 次调�?= 300 �?= 5 分钟
```

**之后**�?
```
3 次调用失败后熔断
总耗时�?-9 �?
节省�?91 秒（97%�?
```

### 案例 3：外�?API 限流

**场景**：外�?API 返回 429 Too Many Requests

**之前**�?
```
持续调用，持续失�?
占用请求配额
```

**之后**�?
```
3 次失败后熔断
5 分钟后恢复（API 限流通常也恢复了�?
```

---

##  工作原理

### 状态机

```
┌─────────────────�?
�? Closed (正常)  �?
�? 失败计数: 0    �?
└────────┬────────�?
         �?
         �?连续失败 >= 3 �?
         �?
┌─────────────────�?
�?  Open (熔断)   �?
�? 拒绝所有调�?  �?
└────────┬────────�?
         �?
         �?超过 5 分钟
         �?
┌─────────────────�?
�? Closed (恢复)  �?
�? 失败计数: 0    �?
└─────────────────�?
```

### 错误判断

熔断器基�?`ToolResponse.status` 判断错误�?

```python
# 工具返回
response = ToolResponse.error(
    code=ToolErrorCode.EXECUTION_ERROR,
    message="执行失败"
)

# 熔断器判�?
if response.status == ToolStatus.ERROR:
    failure_count += 1  # 增加失败计数
```

**优势**�?
- 精确判断（不依赖字符串匹配）
- 支持所有工具类�?
- �?ToolResponse 协议完美集成

---

## �?常见问题

### Q1: 熔断器会影响性能吗？

**A**: 几乎没有影响。熔断器只在工具执行前后做简单的状态检查，开销可忽略不计�?

### Q2: 如何调整熔断阈值？

**A**: 根据工具特性调整：
- **稳定工具**：`failure_threshold=3`（默认）
- **不稳定工�?*：`failure_threshold=5-10`
- **关键工具**：`failure_threshold=1`（一次失败就熔断�?

### Q3: 熔断�?Agent 会怎么做？

**A**: Agent 会收到明确的 `CIRCUIT_OPEN` 错误，可以：
- 尝试其他工具
- 告知用户工具不可�?
- 等待恢复后重�?

### Q4: 可以针对不同工具设置不同阈值吗�?

**A**: 当前版本所有工具共享同一个熔断器配置。如需不同配置，可以创建多�?ToolRegistry�?

### Q5: 熔断器会持久化吗�?

**A**: 当前版本不持久化，重启后状态重置。未来版本可能支持持久化�?

---

##  相关文档

- [工具响应协议](./tool-response-protocol.md)
- [可观测性系统](./observability-guide.md)
- [文件操作工具](./file_tools.md)

---

**最后更�?*�?026-01-19
**维护�?*：MyAgent 开发团�?

