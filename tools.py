"""Phase 9：调查工具（v3：可指定数据源）。

每个工具的固定套路永远是这三样：
  1. Python 函数  —— 真正去查数据
  2. Tool Schema  —— 给 LLM 看的说明书
  3. 注册进 TOOLS / TOOL_SCHEMAS —— 完成"名字 → 函数"的映射

v3 变化：每个函数多了一个 src 参数。
  · src=None  → 查全局 world（原来的行为，侦探 Agent 用）
  · src=副本  → 查这份副本（AI 侦探模式里，玩家会篡改副本）
"""

import world


def _data(src):
    """src 为 None 时用全局 world；否则用传入的数据副本。"""
    return world if src is None else src


def _match_name(mapping, name):
    """在 dict 里按姓名做大小写不敏感的匹配，返回 (真实 key, 值)。"""
    for key, value in mapping.items():
        if key.lower() == name.strip().lower():
            return key, value
    return None, None


# ==================================================================
# 1) Python 函数：真身
# ==================================================================
def search_person(name: str, src=None) -> str:
    """按姓名查询人物档案。"""
    data = _data(src)
    key, person = _match_name(data.PEOPLE, name)
    if person is None:
        return f"没有找到名为 {name!r} 的人物档案。"
    return "\n".join(
        [
            f"姓名：{key}",
            f"身份：{person['role']}",
            f"门禁卡：{person['card']}",
            f"邮箱：{person['email']}",
            f"备注：{person['note']}",
        ]
    )


def search_access_log(target: str, src=None) -> str:
    """按 人 / 卡号 / 地点 / 账号 搜索门禁与服务器访问记录。"""
    data = _data(src)
    needle = target.strip().lower()
    hits = []

    for row in data.ACCESS_LOG:
        blob = f"{row['time']} {row['card']} {row['door']} {row['person']} {row['note']}".lower()
        if needle in blob:
            note = f"（{row['note']}）" if row["note"] else ""
            hits.append(
                f"[门禁] {row['time']} 卡号 {row['card']} → {row['door']}{note}"
            )

    for row in data.SERVER_LOG:
        blob = f"{row['time']} {row['event']}".lower()
        if needle in blob:
            hits.append(f"[服务器] {row['time']} {row['event']}")

    if not hits:
        return f"没有找到与 {target!r} 相关的访问记录。"
    return "\n".join(hits)


def search_message(person: str, src=None) -> str:
    """按姓名查询该人的聊天记录。"""
    data = _data(src)
    key, msgs = _match_name(data.MESSAGES, person)
    if msgs is None:
        return f"没有找到与 {person!r} 相关的聊天记录。"
    lines = [
        f"{m['time']}  → {m['to']}：{m['text']}"
        for m in sorted(msgs, key=lambda m: m["time"])
    ]
    return "\n".join(lines)


def check_alibi(person: str, src=None) -> str:
    """查询某人的证词与其可信度核查。"""
    data = _data(src)
    key, entry = _match_name(data.TESTIMONY, person)
    if entry is None:
        return f"没有找到 {person!r} 的证词。"
    return "\n".join(
        [
            f"{key} 的证词：{entry['claim']}",
            f"可信度：{entry['verdict']}",
            f"核查：{entry['detail']}",
        ]
    )


def search_evidence(keyword: str, src=None) -> str:
    """按关键词搜索物证 / 邮件 / 恢复的数据。"""
    data = _data(src)
    needle = keyword.strip().lower()
    hits = [
        e
        for e in data.EVIDENCE
        if needle in e["id"].lower() or needle in e["text"].lower()
    ]
    if not hits:
        return f"没有找到与 {keyword!r} 相关的物证。"
    return "\n".join(f"[{e['id']}] {e['text']}" for e in hits)


# ==================================================================
# 2) Tool Schema：说明书
# ==================================================================
SEARCH_PERSON_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_person",
        "description": "根据姓名查询人物档案，包括身份、门禁卡号、邮箱和备注。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "人物姓名，例如 'Carol'。"}
            },
            "required": ["name"],
        },
    },
}

SEARCH_ACCESS_LOG_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_access_log",
        "description": (
            "搜索门禁与服务器访问记录。关键词可以是人名、门禁卡号、"
            "地点（如 '服务器机房'）、账号（如 'svc_backup'）或 PIN。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "搜索关键词：人名、卡号、地点、账号或 PIN。",
                }
            },
            "required": ["target"],
        },
    },
}

SEARCH_MESSAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_message",
        "description": "根据姓名查询该人的聊天记录。",
        "parameters": {
            "type": "object",
            "properties": {
                "person": {"type": "string", "description": "人物姓名，例如 'Carol'。"}
            },
            "required": ["person"],
        },
    },
}

CHECK_ALIBI_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_alibi",
        "description": "查询某人的证词（不在场证明）以及该证词的可信度核查。",
        "parameters": {
            "type": "object",
            "properties": {
                "person": {"type": "string", "description": "人物姓名，例如 'David'。"}
            },
            "required": ["person"],
        },
    },
}

SEARCH_EVIDENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_evidence",
        "description": (
            "搜索物证库，包括邮件记录、门禁技术细节、财务线索和已恢复的数据。"
            "关键词可以是人名、物证编号或描述，例如 'David'、'PIN'、'邮件'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词。"}
            },
            "required": ["keyword"],
        },
    },
}


# ==================================================================
# 3) Registry：名字 → 函数
# ==================================================================
TOOLS = {
    "search_person": search_person,
    "search_access_log": search_access_log,
    "search_message": search_message,
    "check_alibi": check_alibi,
    "search_evidence": search_evidence,
}

TOOL_SCHEMAS = [
    SEARCH_PERSON_SCHEMA,
    SEARCH_ACCESS_LOG_SCHEMA,
    SEARCH_MESSAGE_SCHEMA,
    CHECK_ALIBI_SCHEMA,
    SEARCH_EVIDENCE_SCHEMA,
]
