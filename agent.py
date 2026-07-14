from llm import HelloAgentsLLM
from tools import ToolExecutor, search
from re_act import ReActAgent
from plan import PlanAndSolveAgent


def build_react_agent(llm_client: HelloAgentsLLM, max_steps: int = 5) -> ReActAgent:
    """构建 ReAct 智能体，并注册可用工具。"""
    tool_executor = ToolExecutor()
    tool_executor.registerTool(
        name="search",
        description="网页搜索工具，输入查询关键词，返回搜索结果摘要。",
        func=search
    )
    return ReActAgent(llm_client=llm_client, tool_executor=tool_executor, max_steps=max_steps)


def build_plan_agent(llm_client: HelloAgentsLLM) -> PlanAndSolveAgent:
    """构建 Plan-and-Solve 智能体。"""
    return PlanAndSolveAgent(llm_client=llm_client)


def run_agent(agent, question: str):
    """运行指定的智能体并打印结果。"""
    answer = agent.run(question)
    print("\n========== 最终结果 ==========")
    print(answer if answer else "未能获得答案。")


def main():
    # 初始化LLM客户端（配置从 .env 读取）
    llm_client = HelloAgentsLLM()

    print("智能体已启动。")
    print("可用模式:")
    print("  - react  : ReAct 智能体（推理+行动，可调用工具）")
    print("  - plan   : Plan-and-Solve 智能体（先规划后执行）")
    print("命令:")
    print("  :mode react   切换为 ReAct 模式")
    print("  :mode plan    切换为 Plan 模式")
    print("  exit / quit   退出")

    # 默认使用 ReAct
    current_mode = "react"
    agent = build_react_agent(llm_client)
    print(f"\n当前模式: {current_mode}")

    while True:
        question = input("\n请输入你的问题: ").strip()
        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            print("再见！")
            break

        # 切换模式命令
        if question.lower().startswith(":mode"):
            parts = question.split(maxsplit=1)
            if len(parts) < 2:
                print("用法: :mode react  或  :mode plan")
                continue
            mode = parts[1].strip().lower()
            if mode == "react":
                agent = build_react_agent(llm_client)
                current_mode = "react"
                print(f"已切换为 ReAct 模式。")
            elif mode == "plan":
                agent = build_plan_agent(llm_client)
                current_mode = "plan"
                print(f"已切换为 Plan 模式。")
            else:
                print(f"未知模式: {mode}，可选: react, plan")
            continue

        print(f"\n用户问题: {question}  [模式: {current_mode}]\n")
        run_agent(agent, question)


if __name__ == "__main__":
    main()
