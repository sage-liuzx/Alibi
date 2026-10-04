"""Phase 3：LLM 调用封装（改用 openai SDK）。

和 Phase 1 的关键区别：
  Phase 1 只返回 content（一段文本）
  Phase 3 返回整条 message —— 因为 tool_calls 藏在 message 里，不在 content 里
"""

import os

from openai import OpenAI, OpenAIError

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 调用参数：超时防止无限挂起；max_tokens 防止回答被悄悄截断
DEFAULT_TIMEOUT = 60        # 秒
DEFAULT_MAX_TOKENS = 4096


def load_env(path=_ENV_PATH):
    """（与 Phase 1 相同）把 .env 里的 KEY=VALUE 读进 os.environ。"""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name):
    """读一个必填环境变量，缺了就立刻报错（fail fast）。"""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}。请检查 .env 文件。")
    return value


def call_llm(messages, tools=None, max_tokens=DEFAULT_MAX_TOKENS, tool_choice=None):
    """把 messages（可选带 tools）发给 LLM。

    返回值变了：现在返回一个 dict
        {"message": <助手消息对象>, "finish_reason": <停止原因>}
    因为调用方必须能读到 finish_reason，才能发现"回答被截断"这类问题。

    tool_choice：可强制模型必须调用某个工具（审讯模式的"时间到必须收网"就靠它）。
    """
    client = OpenAI(
        api_key=_env("OPENAI_API_KEY"),
        base_url=_env("OPENAI_BASE_URL"),
        timeout=DEFAULT_TIMEOUT,   # P0 修复：兜底超时，防止请求无限挂起
    )

    request = {
        "model": _env("OPENAI_MODEL"),
        "messages": messages,
        "max_tokens": max_tokens,  # P0 修复：显式限制输出长度，避免默认值过小而截断
    }
    if tools:
        request["tools"] = tools
    if tool_choice:
        request["tool_choice"] = tool_choice

    # **request 把字典拆成关键字参数传进去（Phase 5 也会用到这个技巧）
    try:
        response = client.chat.completions.create(**request)
    except OpenAIError as e:
        # P0 修复：把 SDK 的各种异常（限流/超时/连接失败/参数错…）统一成一种，
        # 调用方只需处理 RuntimeError，且错误信息里保留原始异常类型。
        raise RuntimeError(f"LLM API 调用失败：{type(e).__name__}: {e}") from e

    choice = response.choices[0]
    return {"message": choice.message, "finish_reason": choice.finish_reason}
