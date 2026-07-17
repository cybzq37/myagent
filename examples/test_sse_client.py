"""SSE 客户端测试脚本"""

import requests
import json

def test_sse_stream(input_text: str, agent_type: str = "react"):
    """测试 SSE 流式输出"""
    url = "http://localhost:8000/agent/stream"
    
    payload = {
        "input": input_text,
        "agent_type": agent_type
    }
    
    print(f" 发送请求: {input_text}")
    print(f" Agent类型: {agent_type}")
    print("-" * 60)
    
    try:
        response = requests.post(
            url,
            json=payload,
            stream=True,
            headers={"Accept": "text/event-stream"}
        )
        
        if response.status_code != 200:
            print(f" 错误: {response.status_code} - {response.text}")
            return
        
        # 逐行读取 SSE 事件
        for line in response.iter_lines(decode_unicode=True):
            if line:
                print(line)
                
    except KeyboardInterrupt:
        print("\n 用户中断")
    except Exception as e:
        print(f" 异常: {e}")

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        ("计算 123 + 456", "react"),
        ("你好，介绍一下你自己", "simple"),
        ("分析一下人工智能的发展趋势", "reflection"),
    ]
    
    for input_text, agent_type in test_cases:
        test_sse_stream(input_text, agent_type)
        print("\n" + "=" * 60 + "\n")

