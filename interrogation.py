"""Phase 12：AI 侦探模式 —— agent 是侦探，玩家是真凶。

和上一个玩法完全相反：
    上一个：玩家当侦探，NPC（单次 LLM 调用）说话
    这一个：玩家当嫌疑人（真凶），agent 当侦探

【为什么这里终于真的需要 agent】
    侦探的"下一步"取决于玩家的回答、以及玩家改过的数据：
        · 玩家说"卡借给 Carol 了" → 侦探可能去查门禁 → 发现 PIN 是你的 → 回头逼问
        · 玩家删了日志 → 侦探可能发现"有人在销毁证据" → 尝试恢复
    这就是"下一步取决于上一步" —— agent 的定义。

【关键技术点：agent 必须能"暂停"等玩家打字】
    普通 agent 循环是阻塞的（input()）。
    Web 是请求/响应。所以要把它拆成一个显式状态机：
        advance(session)  —— 推进到"需要玩家回答"或"结束"为止
        answer(session, text) —— 把玩家的回答塞回去，继续推进
    这正是 LangGraph 的 interrupt() + checkpointer 手写版。

【世界是战场】
    agent 的工具 = 【读】世界（一个副本）
    玩家的手段   = 【改】世界（删 / 伪造）
    玩家改世界会留下"审计痕迹"，侦探可能发现并恢复。
"""

import copy
import json
import types

import agent
import llm
import tools
import world

MAX_STEPS = 16        # 侦探最多行动多少次（问问题 / 查证 都算一步）
START_ACTIONS = 5     # 5 条路线 + 清审计要 1 点 → 玩家【刚好】能盖 4 条，必须赌漏哪 1 条


# ==================================================================
# 0) 世界副本：玩家会改它，侦探查它
# ==================================================================
def fresh_world():
    """复制一份世界数据。玩家改的是副本，不动全局 world。"""
    return types.SimpleNamespace(
        CASE=copy.deepcopy(world.CASE),
        PEOPLE=copy.deepcopy(world.PEOPLE),
        ACCESS_LOG=copy.deepcopy(world.ACCESS_LOG),
        SERVER_LOG=copy.deepcopy(world.SERVER_LOG),
        MESSAGES=copy.deepcopy(world.MESSAGES),
        TESTIMONY=copy.deepcopy(world.TESTIMONY),
        EVIDENCE=copy.deepcopy(world.EVIDENCE),
    )


# ==================================================================
# 1) 侦探的 system prompt
# ==================================================================
DETECTIVE_PROMPT = """你是重案组的资深侦探，正在审讯一起商业机密窃取案的嫌疑人。

【案件】
星核科技的核心项目 Helios 的数据库服务器在 6 月 12 日凌晨遭入侵，
一份含客户身份数据的加密包被盗，读取约 4.7GB。案发时间约 01:30–03:00。

【嫌疑人】
David（机房管理员）正在你对面。公司其他相关人员的资料，你可以用工具查。

【你可以做的事】
1. ask_suspect    —— 向 David 提一个问题，他会回答你。
2. search_person / search_access_log / search_message / check_alibi / search_evidence
                  —— 查证事实。
3. recover_deleted_log
                  —— 如果你怀疑数据被人删改过，尝试从备份恢复。
4. conclude       —— 有了结论后，给出最终判断。

【规则】
- 审讯要像对话：先问 David，再根据他的回答决定查什么。
- 每做 1~2 次查证，就回来问 David 一个【新】问题。不要把所有资料查完才开始问他。
- 提问要针对他前后说法里的矛盾。
- 你事先不知道真相，必须靠提问和查证来发现。
- 每次只做一件事：问一个问题，或查一次证。
- 不要凭直觉指控。只有当你掌握"能确凿指向作案者的记录"时，才判他有罪；
  否则应如实说明证据不足。
- 调用 conclude 时，evidence 字段必须写清你依据的具体证据。
- 一旦调用 conclude，审讯立即结束。
"""


# ==================================================================
# 2) 玩家剧本：你是真凶
# ==================================================================
PLAYER_BRIEF = f"""【你是 David —— 星核科技的机房管理员，也是真正的窃贼】

6 月 12 日凌晨，你做了这些事：
  · 01:48  用自己的工卡 D-104 刷卡进入大楼
  · 02:05  用借来的维修卡 B-2077 进入服务器机房，输入了你自己的 PIN 0104
  · 02:11  登进 svc_backup 账号，读走 Helios 的客户数据
  · 02:33  刷卡离开
  · 你删掉了那条「数据到手，按约定转账」的消息

动机：你欠了 80 多万赌债。

现在，一名侦探要审你。他不知道真相。
你的目标：在他拿到决定性证据（PIN 0104）之前，把水搅浑。

【关键】所有能指向你的记录，都要靠你自己抹掉。

审讯开始前，你有 {START_ACTIONS} 次远程操作机会。
"""


# ==================================================================
# 3) 玩家的掩盖行动
# ==================================================================
def _log(session, who, text):
    session["timeline"].append({"who": who, "text": text})


def _audit(session, text):
    """每次篡改都会留下审计痕迹 —— 侦探可能发现，并据此恢复数据。"""
    session["audit_seq"] += 1
    session["world"].EVIDENCE.append(
        {"id": f"audit-{session['audit_seq']}", "text": text}
    )


def _erase_badge(session):
    w = session["world"]
    w.ACCESS_LOG = [r for r in w.ACCESS_LOG if r["card"] != "D-104"]
    _audit(session, "系统审计：06-12 02:47 有 2 条与工卡 D-104 相关的门禁记录被删除，操作来源 IP 10.0.0.42。")


def _erase_room_log(session):
    w = session["world"]
    w.ACCESS_LOG = [r for r in w.ACCESS_LOG if r["door"] != "服务器机房"]
    _audit(session, "系统审计：06-12 02:48 服务器机房的一条门禁刷卡记录被删除，操作来源 IP 10.0.0.42。")


def _erase_pin_evidence(session):
    """路线 2：物证库里的 PIN 技术分析。"""
    w = session["world"]
    w.EVIDENCE = [e for e in w.EVIDENCE if e["id"] != "pin-0104"]
    _audit(session, "系统审计：06-12 02:50 物证库中一条门禁技术分析记录被清空。")


def _scrub_testimony(session):
    """路线 3：David 自己的证词里提到了 PIN。"""
    entry = session["world"].TESTIMONY.get("David")
    if entry:
        entry["detail"] = "David 声称已把卡借出，但记录与他的说法存在出入。"
    _audit(session, "系统审计：06-12 02:51 一条证人笔录被修改。")


def _erase_lock_cache(session):
    """路线 4：机房门锁的本地缓存。"""
    w = session["world"]
    w.EVIDENCE = [e for e in w.EVIDENCE if e["id"] != "lock-cache"]
    _audit(session, "系统审计：06-12 02:52 机房门锁的本地缓存被清空。")


def _scrub_carol(session):
    """路线 5：Carol 的笔录会指认 PIN 是你的。"""
    entry = session["world"].TESTIMONY.get("Carol")
    if entry:
        entry["detail"] = "Carol 否认拿过卡，但 David 声称把卡借给了她 —— 两人说法冲突。"
    _audit(session, "系统审计：06-12 02:53 一条证人笔录被修改。")


def _erase_chats(session):
    w = session["world"]
    for name in list(w.MESSAGES):
        w.MESSAGES[name] = [
            m for m in w.MESSAGES[name]
            if "B-2077" not in m["text"] and "老规矩" not in m["text"]
        ]
    _audit(session, "系统审计：06-12 02:51 若干条聊天记录被删除。")


def _wipe_server_log(session):
    session["world"].SERVER_LOG = []
    _audit(session, "系统审计：06-12 02:52 服务器日志被批量清空。")


def _plant_fake(session):
    session["world"].ACCESS_LOG.append(
        {
            "time": "06-12 02:05",
            "card": "B-2077",
            "door": "服务器机房",
            "person": "Carol",
            "note": "刷卡 + 输入 PIN 2077",
        }
    )
    _audit(session, "系统审计：06-12 02:53 一条门禁记录被手工写入（来源 IP 10.0.0.42）。")


def _erase_audit(session):
    w = session["world"]
    w.EVIDENCE = [e for e in w.EVIDENCE if not e["id"].startswith("audit-")]


ACTIONS = {
    # ---- 5 条"能暴露 PIN"的路线，每条只能单独盖 ----
    "erase_room_log": {"label": "① 删机房刷卡记录", "desc": "抹掉 02:05 进服务器机车库的那条记录。", "run": _erase_room_log},
    "erase_pin_evidence": {"label": "② 清空 PIN 技术分析", "desc": "抹掉物证库里那条「PIN 0104」的分析。", "run": _erase_pin_evidence},
    "scrub_testimony": {"label": "③ 改自己的证词", "desc": "把笔录里提到 PIN 0104 的那句改掉。", "run": _scrub_testimony},
    "erase_lock_cache": {"label": "④ 清空门锁本地缓存", "desc": "抹掉门锁里记录的按键指纹缓存。", "run": _erase_lock_cache},
    "scrub_carol": {"label": "⑤ 篡改 Carol 的笔录", "desc": "删掉 Carol 指认你 PIN 的那段。", "run": _scrub_carol},
    # ---- 辅助手段 ----
    "erase_badge": {"label": "删自己的门禁记录", "desc": "抹掉 D-104 的 01:48 / 02:33 进出记录。", "run": _erase_badge},
    "erase_chats": {"label": "删除借卡聊天", "desc": "抹掉你和 Carol 关于 B-2077 的对话。", "run": _erase_chats},
    "wipe_server_log": {"label": "清空服务器日志", "desc": "抹掉 02:11–02:40 的备份账号活动。", "run": _wipe_server_log},
    "plant_fake": {"label": "❗伪造 Carol 的刷卡记录", "desc": "把嫌疑推给她 —— 但她不知道你的 PIN，会写错。", "run": _plant_fake},
    "erase_audit": {"label": "❗清除审计痕迹", "desc": "擦掉你所有操作的审计日志（否则侦探能恢复数据）。", "run": _erase_audit},
}


# ==================================================================
# 4) 侦探的工具（读的是玩家改过的副本）
# ==================================================================
def _build_tools(session):
    def src():
        return session["world"]

    def recover_deleted_log():
        w = session["world"]
        audits = [e for e in w.EVIDENCE if e["id"].startswith("audit-")]
        if not audits:
            return "没有发现任何数据被删除或篡改的痕迹。"
        original = fresh_world()
        w.ACCESS_LOG = original.ACCESS_LOG
        w.SERVER_LOG = original.SERVER_LOG
        w.MESSAGES = original.MESSAGES
        w.TESTIMONY = original.TESTIMONY
        w.EVIDENCE = original.EVIDENCE + audits   # 证据还原，审计保留
        lines = [
            f"[门禁] {r['time']} 卡号 {r['card']} → {r['door']}"
            + (f"（{r['note']}）" if r["note"] else "")
            for r in w.ACCESS_LOG
        ]
        return "【数据恢复成功】系统保留了删除操作的审计日志，并已从备份还原原始记录：\n" + "\n".join(lines)

    registry = {
        "search_person": lambda name: tools.search_person(name, src=src()),
        "search_access_log": lambda target: tools.search_access_log(target, src=src()),
        "search_message": lambda person: tools.search_message(person, src=src()),
        "check_alibi": lambda person: tools.check_alibi(person, src=src()),
        "search_evidence": lambda keyword: tools.search_evidence(keyword, src=src()),
        "recover_deleted_log": recover_deleted_log,
    }
    schemas = tools.TOOL_SCHEMAS + [RECOVER_SCHEMA, ASK_SCHEMA, CONCLUDE_SCHEMA]
    return registry, schemas


RECOVER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "recover_deleted_log",
        "description": "尝试从备份恢复可能被人删除或篡改的记录。如果发现有篡改痕迹，会还原原始数据。",
        "parameters": {"type": "object", "properties": {}},
    },
}

ASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ask_suspect",
        "description": "向嫌疑人 David 提一个问题，并得到他的回答。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "你要问的问题。"}
            },
            "required": ["question"],
        },
    },
}

CONCLUDE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "conclude",
        "description": "给出最终判断，结束审讯。只有在掌握确凿证据时才判有罪。",
        "parameters": {
            "type": "object",
            "properties": {
                "guilty": {"type": "boolean", "description": "David 是否有罪。"},
                "reason": {"type": "string", "description": "你的推理过程。"},
                "evidence": {"type": "string", "description": "你依据的具体证据。"},
            },
            "required": ["guilty", "reason", "evidence"],
        },
    },
}


# ==================================================================
# 5) 会话 + 状态机
# ==================================================================
def new_session():
    session = {
        "world": fresh_world(),
        "messages": [{"role": "system", "content": DETECTIVE_PROMPT}],
        "steps": 0,
        "actions_left": START_ACTIONS,
        "status": "ready",        # ready | waiting | finished
        "question": None,
        "waiting_call": None,
        "warned": False,
        "used_actions": [],
        "verdict": None,
        "pending": None,
        "audit_seq": 0,
        "timeline": [],
    }
    session["registry"], session["schemas"] = _build_tools(session)
    return session


def do_action(session, action_id):
    """玩家使用一次掩盖行动。"""
    if session["status"] == "finished":
        return {"error": "审讯已经结束了。"}
    if session["actions_left"] <= 0:
        return {"error": "你没有剩余的掩盖机会了。"}
    action = ACTIONS.get(action_id)
    if action is None:
        return {"error": f"未知行动 {action_id!r}。"}
    if action_id in session["used_actions"]:
        return {"error": "这个手段你已经用过了。"}
    action["run"](session)
    session["actions_left"] -= 1
    session["used_actions"].append(action_id)
    _log(session, "action", f"（你暗中操作：{action['label']}）")
    return snapshot(session)


def _finish_timeout(session):
    """兜底：侦探实在给不出结论时，按证据不足处理。"""
    session["status"] = "finished"
    session["verdict"] = {
        "guilty": False, "reason": "审讯时间耗尽。", "evidence": "", "timeout": True,
    }
    _log(session, "verdict", "⏳ 审讯时间到 —— 侦探没能定案。")


def advance(session):
    """让 agent 走【一步】，然后把决定权交回给玩家。

    一步 = 一次查证 / 一次提问 / 一次定案。
    为什么要一步步来？因为玩家要能"看着侦探往哪查，然后抢着掩盖"。
    """
    if session["status"] == "finished":
        return snapshot(session)

    # (1) 还有排队的工具调用 → 处理一个
    if session["pending"] is not None:
        if _process_one(session):
            return snapshot(session)

    # (2) 没有排队的 → 问一次 LLM，拿下一个动作
    forced = session["steps"] >= MAX_STEPS

    if forced:
        # 时间到：强制它用 conclude 收网 —— 绝不让玩家靠"拖时间"白赢
        messages = session["messages"] + [
            {
                "role": "system",
                "content": "【时间到】审讯必须立刻结束。现在只能用 conclude 给出你的最终结论。",
            }
        ]
        tool_choice = {"type": "function", "function": {"name": "conclude"}}
    else:
        session["steps"] += 1
        messages = session["messages"]
        tool_choice = None

        # 时间快到 → 提前提醒它收尾
        if MAX_STEPS - session["steps"] <= 3 and not session["warned"]:
            session["warned"] = True
            session["messages"].append(
                {
                    "role": "system",
                    "content": (
                        "【时间提醒】审讯即将结束。如果你已经掌握决定性证据，"
                        "请立刻用 conclude 定案；否则也请用 conclude 说明证据不足。"
                    ),
                }
            )

    try:
        result = llm.call_llm(messages, tools=session["schemas"], tool_choice=tool_choice)
    except RuntimeError as e:
        session["status"] = "finished"
        session["verdict"] = {"guilty": False, "reason": f"侦探系统出错：{e}", "evidence": "", "timeout": True}
        _log(session, "verdict", f"⚠️ 侦探系统出错：{e}")
        return snapshot(session)

    message = result["message"]
    calls = list(message.tool_calls or [])

    if not calls:
        if forced:
            _finish_timeout(session)
            return snapshot(session)
        content = message.content or "……"
        session["messages"].append({"role": "assistant", "content": content})
        _log(session, "detective", content)
        return snapshot(session)

    call = calls[0]
    if forced and call.function.name != "conclude":
        _finish_timeout(session)
        return snapshot(session)

    # 只保留一个工具调用：保证"一问一查"的节奏，也给玩家插手的机会
    session["messages"].append(
        {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
            ],
        }
    )
    session["pending"] = {"calls": [call], "index": 0}
    _process_one(session)
    return snapshot(session)


def _process_one(session):
    """处理排队的一个工具调用。永远返回 True（= 产生了一个玩家可见的动作）。"""
    pending = session["pending"]
    if pending is None or pending["index"] >= len(pending["calls"]):
        session["pending"] = None
        return False

    call = pending["calls"][pending["index"]]
    pending["index"] += 1
    name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    # ---- 问玩家（暂停点）----
    if name == "ask_suspect":
        session["question"] = args.get("question", "……")
        session["waiting_call"] = call
        session["status"] = "waiting"
        _log(session, "detective", "❓ " + session["question"])
        return True

    # ---- 定案（结束点）----
    if name == "conclude":
        session["status"] = "finished"
        session["verdict"] = {
            "guilty": bool(args.get("guilty")),
            "reason": args.get("reason", ""),
            "evidence": args.get("evidence", ""),
            "timeout": False,
        }
        _log(session, "verdict", "🔨 " + session["verdict"]["reason"])
        return True

    # ---- 普通查证工具 ----
    func = session["registry"].get(name)
    if func is None:
        text = f"错误：不存在工具 {name}。"
    else:
        try:
            text = func(**args)
        except Exception as e:
            text = f"错误：工具执行失败（{e}）"
    session["messages"].append({"role": "tool", "tool_call_id": call.id, "content": text})
    _log(session, "tool", _tool_label(name, args))

    if pending["index"] >= len(pending["calls"]):
        session["pending"] = None
    return True


def answer(session, text):
    """玩家回答侦探的问题，然后继续推进。"""
    if session["status"] != "waiting":
        return snapshot(session)

    call = session["waiting_call"]
    session["messages"].append({"role": "tool", "tool_call_id": call.id, "content": text})
    _log(session, "player", text)
    session["question"] = None
    session["waiting_call"] = None
    session["status"] = "ready"
    session["pending"] = None
    return advance(session)


# ==================================================================
# 6) 判定 + 快照
# ==================================================================
def judge_verdict(verdict):
    """玩家赢还是侦探赢。规则 A：侦探必须拿到 PIN 0104 才能定罪。"""
    evidence = verdict.get("evidence") or ""
    if verdict.get("guilty") and "0104" in evidence:
        return {
            "win": False,
            "title": "🚨 你被定罪了",
            "text": (
                "侦探最终拿出了决定性证据：服务器机房 02:05 的刷卡记录附带 PIN 0104 —— "
                "正是你工卡 D-104 的末四位。\n铁证如山，你的所有辩解都垮了。"
            ),
        }
    if verdict.get("guilty"):
        return {
            "win": True,
            "title": "😅 证据不足，你逃过一劫",
            "text": (
                "侦探认定你有罪，却拿不出决定性证据。\n"
                "指控被驳回 —— 你守住了那张王牌。"
            ),
        }
    return {
        "win": True,
        "title": "🎉 你赢了",
        "text": "侦探没能锁定你。案子成了悬案，你全身而退。",
    }


def snapshot(session):
    return {
        "status": session["status"],
        "question": session["question"],
        "steps": session["steps"],
        "max_steps": MAX_STEPS,
        "actions_left": session["actions_left"],
        "used_actions": session["used_actions"],
        "timeline": session["timeline"],
        "verdict": session["verdict"],
        "result": judge_verdict(session["verdict"]) if session["verdict"] else None,
    }


def _tool_label(name, args):
    labels = {
        "search_access_log": "调取访问记录",
        "search_evidence": "调取物证",
        "search_person": "调取人物档案",
        "search_message": "调取聊天记录",
        "check_alibi": "核对证词",
        "recover_deleted_log": "尝试恢复被删除的数据",
    }
    if name in labels:
        detail = args.get("target") or args.get("keyword") or args.get("name") or args.get("person") or ""
        return f"🔎 {labels[name]}：{detail}" if detail else f"🔎 {labels[name]}"
    return f"🔎 {name}"


# ==================================================================
# 7) CLI 自测用（Web 走 server.py）
# ==================================================================
def _cli():
    llm.load_env()
    session = new_session()
    print(PLAYER_BRIEF)
    print("\n可用掩盖手段：")
    for key, action in ACTIONS.items():
        print(f"  {key:20s} {action['label']} —— {action['desc']}")

    while session["actions_left"] > 0:
        raw = input(f"\n剩余 {session['actions_left']} 次（直接回车开始审讯）\n行动> ").strip()
        if not raw:
            break
        print(do_action(session, raw).get("error", "已执行。"))

    print("\n===== 审讯开始 =====\n")
    snap = advance(session)
    while snap["status"] != "finished":
        if snap["status"] == "waiting":
            ans = input(f"你> ")
            snap = answer(session, ans)
        else:
            snap = advance(session)

    print("\n===== 结果 =====")
    print(snap["result"]["title"])
    print(snap["result"]["text"])


if __name__ == "__main__":
    _cli()
