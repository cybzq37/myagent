"""异常体系"""

class MyAgentException(Exception):
    """MyAgent基础异常类"""
    pass

class LLMException(MyAgentException):
    """LLM相关异常"""
    pass

class AgentException(MyAgentException):
    """Agent相关异常"""
    pass

class ConfigException(MyAgentException):
    """配置相关异常"""
    pass

class ToolException(MyAgentException):
    """工具相关异常"""
    pass
