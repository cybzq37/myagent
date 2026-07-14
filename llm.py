import os
from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict, Optional

# 加载 .env 文件中的环境变量
load_dotenv()

class HelloAgentsLLM:
    """
    为本书 "Hello Agents" 定制的LLM客户端。
    它用于调用任何兼容OpenAI接口的服务，并默认使用流式响应。
    同时支持 Chat Completions API 和 Responses API 两种格式。
    """
    def __init__(self, model: str = None, apiKey: str = None, baseUrl: str = None,
                 timeout: int = None, api_format: str = None):
        """
        初始化客户端。优先使用传入参数，如果未提供，则从环境变量加载。

        参数:
            api_format: API 格式，可选值为 "chat_completions" 或 "responses"。
                        默认从环境变量 LLM_API_FORMAT 读取，未配置时默认 "chat_completions"。
        """
        self.model = model or os.getenv("LLM_MODEL_ID")
        apiKey = apiKey or os.getenv("LLM_API_KEY")
        baseUrl = baseUrl or os.getenv("LLM_BASE_URL")
        timeout = timeout or int(os.getenv("LLM_TIMEOUT", 60))

        # 决定使用哪种 API 格式:参数优先，其次环境变量，默认 chat_completions
        self.api_format = (api_format or os.getenv("LLM_API_FORMAT") or "chat_completions").lower()
        if self.api_format not in ("chat_completions", "responses"):
            raise ValueError(f"不支持的 api_format: {self.api_format}，可选值: chat_completions, responses")

        if not all([self.model, apiKey, baseUrl]):
            raise ValueError("模型ID、API密钥和服务地址必须被提供或在.env文件中定义。")

        self.client = OpenAI(api_key=apiKey, base_url=baseUrl, timeout=timeout)

    def think(self, messages: List[Dict[str, str]], temperature: float = 0,
              api_format: str = None) -> str:
        """
        调用大语言模型进行思考，并返回其响应。

        参数:
            messages: 消息列表，格式为 [{"role": "...", "content": "..."}]。
            temperature: 采样温度，控制输出随机性。
            api_format: 临时覆盖 API 格式，可选 "chat_completions" 或 "responses"。
                        None 表示用初始化时的配置。
        """
        fmt = (api_format or self.api_format).lower()
        if fmt == "responses":
            return self._think_responses(messages, temperature)
        elif fmt == "chat_completions":
            return self._think_chat_completions(messages, temperature)
        else:
            raise ValueError(f"不支持的 api_format: {fmt}，可选值: chat_completions, responses")

    def _think_chat_completions(self, messages: List[Dict[str, str]], temperature: float) -> str:
        """使用 Chat Completions API 调用模型（经典格式）。"""
        print(f"正在调用 {self.model} 模型 [Chat Completions]...")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
            )

            print("大语言模型响应成功:")
            collected_content = []
            for chunk in response:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content or ""
                print(content, end="", flush=True)
                collected_content.append(content)
            print()
            return "".join(collected_content)

        except Exception as e:
            print(f"调用LLM API时发生错误: {e}")
            return None

    def _think_responses(self, messages: List[Dict[str, str]], temperature: float) -> str:
        """使用 Responses API 调用模型（新格式，兼容 Chat 消息数组）。"""
        print(f"正在调用 {self.model} 模型 [Responses API]...")
        try:
            response = self.client.responses.create(
                model=self.model,
                input=messages,
                temperature=temperature,
                stream=True,
            )

            print("大语言模型响应成功:")
            collected_content = []
            for event in response:
                # Responses API 流式事件:text 增量在 response.output_text.delta 事件中
                if event.type == "response.output_text.delta":
                    print(event.delta, end="", flush=True)
                    collected_content.append(event.delta)
            print()
            return "".join(collected_content)

        except Exception as e:
            print(f"调用LLM API时发生错误: {e}")
            return None

# --- 客户端使用示例 ---
if __name__ == '__main__':
    try:
        exampleMessages = [
            {"role": "system", "content": "You are a helpful assistant that writes Python code."},
            {"role": "user", "content": "写一个快速排序算法"}
        ]

        # 示例1:使用 Chat Completions API（默认）
        print("=" * 50)
        print("示例1: Chat Completions API")
        print("=" * 50)
        llmClient = HelloAgentsLLM(api_format="chat_completions")
        responseText = llmClient.think(exampleMessages)
        if responseText:
            print(f"\n\n--- 完整模型响应 ---")
            print(responseText)

        # 示例2:使用 Responses API
        print("\n" + "=" * 50)
        print("示例2: Responses API")
        print("=" * 50)
        llmClient2 = HelloAgentsLLM(api_format="responses")
        responseText2 = llmClient2.think(exampleMessages)
        if responseText2:
            print(f"\n\n--- 完整模型响应 ---")
            print(responseText2)

    except ValueError as e:
        print(e)
