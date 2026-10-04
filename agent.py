"""Phase 7：Agent Loop —— 把前面所有零件串起来。

它做的事用一句话概括：
    反复问 LLM
      → 如果它要调工具，就执行工具
      → 把结果塞回 messages
      → 再问
    直到 LLM 不再要工具（= 给出最终答案），或者到达 MAX_STEPS。
"""

import json

import llm
import tools

MAX_STEPS = 10


def execute_tool(tool_call, registry=None):
    """执行一次工具调用，永远返回字符串（成功结果或错误说明）。

    registry 可选：不传就用全局 tools.TOOLS。
    传进来 → 同一个 Agent Loop 可以换成任意一套工具（NPC 的、侦探的……）。
    """
    registry = tools.TOOLS if registry is None else registry
    name = tool_call.function.name

    # 1) 名字 → 函数。这就是 Phase 4 的 Registry 在起作用。
    func = registry.get(name)
    if func is None:
        return f"错误：不存在名为 {name} 的工具。"

    # 2) 字符串参数 → dict（Phase 3 看到的那个坑，这里正式处理）
    try:
        args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as e:
        return f"错误：参数不是合法 JSON（{e}）。"

    # 3) 真正执行。**args 把 dict 拆成关键字参数
    try:
        return func(**args)
    except TypeError as e:
        return f"错误：参数与工具定义不匹配（{e}）。"
    except Exception as e:
        return f"错误：工具执行失败（{e}）。"


def _assistant_message(message):
    """把 SDK 的 message 对象转成可以放回 messages 的纯 dict。"""
    return {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ],
    }


def run_agent(user_input, system=None, messages=None, max_steps=MAX_STEPS,
              registry=None, tool_schemas=None):
    """跑一轮完整的 Agent，返回最终文本答案。

    system       —— 可选的人设/角色设定（system prompt），用于 NPC 等场景。
    messages     —— 可选的既有对话历史。传同一个 list 进来，Agent 就能记住跨轮对话。
    registry     —— 可选：这次能用的工具集（名字 → 函数）。默认全局 tools.TOOLS。
    tool_schemas —— 可选：给 LLM 的工具说明书。默认全局 tools.TOOL_SCHEMAS。
    """
    if registry is None:
        registry = tools.TOOLS
    if tool_schemas is None:
        tool_schemas = tools.TOOL_SCHEMAS

    if messages is None:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})

    for step in range(max_steps):
        print(f"\n--- step {step + 1}/{max_steps} ---")

        try:
            result = llm.call_llm(messages, tools=tool_schemas)
        except RuntimeError as e:
            # P0 修复：API 出错不再让整个 Agent 崩掉，而是给出明确交代
            print(f"  [error] {e}")
            return f"（Agent 无法完成本次请求：{e}）"

        message = result["message"]
        finish_reason = result["finish_reason"]

        # P0 修复：被长度截断时，绝不能把半句话当成最终答案返回
        if finish_reason == "length":
            print("  [warn] finish_reason=length，回答被截断")
            partial = message.content or ""
            return partial + "\n\n（注意：本条回答因达到 max_tokens 上限被截断，内容不完整。）"

        # 没有工具调用 → 这就是最终答案，收工
        if not message.tool_calls:
            print(f"  [final] {message.content}")
            return message.content

        # 有工具调用 → 先把模型这句话本身放回历史（否则下一轮它会"忘"了自己请求过什么）
        messages.append(_assistant_message(message))

        # 逐个执行工具，把结果作为 role=tool 的消息放回历史
        for tool_call in message.tool_calls:
            print(f"  [tool] {tool_call.function.name}({tool_call.function.arguments})")
            result = execute_tool(tool_call, registry)
            print(f"  [result] {result}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,   # 用 id 和这次调用配对
                    "content": result,
                }
            )

    return "（达到 MAX_STEPS，Agent 停止：本轮没有得出最终答案。）"
