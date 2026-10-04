"""AI 侦探调查游戏 —— 真人可玩版。

运行：
    cd /workspace/alibi
    python3 game.py

你是侦探。目标是找出真凶，并拿出决定性证据。

命令（游戏内输入 /help 也能看）：
    /suspects              列出嫌疑人
    /investigate <关键词>   搜索线索（门禁 / 服务器 / 物证 / 聊天 / 证词）
    /profile <名字>        查看某人的档案（会记进笔记本）
    /talk <名字>           盘问某位嫌疑人（/back 结束盘问）
    /notebook              查看你已收集的线索
    /accuse <名字>         指认凶手（游戏结束）
    /quit                  退出
"""

import llm
import npc
import world


# ==================================================================
# 确定性层
# ==================================================================
def resolve_name(raw, mapping):
    """大小写不敏感地把玩家输入解析成真实的名字。"""
    for key in mapping:
        if key.lower() == raw.strip().lower():
            return key
    return None


def investigate(keyword):
    """在所有世界数据里搜索关键词，返回线索文本列表。"""
    needle = keyword.strip().lower()
    hits = []

    for row in world.ACCESS_LOG:
        blob = f"门禁 刷卡记录 {row['time']} {row['card']} {row['door']} {row['person']} {row['note']}".lower()
        if needle in blob:
            note = f"（{row['note']}）" if row["note"] else ""
            hits.append(f"[门禁] {row['time']} 卡号 {row['card']} → {row['door']}{note}")

    for row in world.SERVER_LOG:
        blob = f"服务器 日志 {row['time']} {row['event']}".lower()
        if needle in blob:
            hits.append(f"[服务器] {row['time']} {row['event']}")

    for name, person in world.PEOPLE.items():
        blob = f"档案 人物 {name} {person['role']} {person.get('note', '')}".lower()
        if needle in blob:
            hits.append(f"[档案] {name}：{person['role']}。{person.get('note', '')}")

    for item in world.EVIDENCE:
        blob = f"物证 {item['id']} {item['text']}".lower()
        if needle in blob:
            hits.append(f"[物证] {item['text']}")

    for name, msgs in world.MESSAGES.items():
        for m in msgs:
            blob = f"{name} {m['time']} {m['to']} {m['text']}".lower()
            if needle in blob:
                hits.append(f"[聊天] {name} → {m['to']}（{m['time']}）：{m['text']}")

    for name, t in world.TESTIMONY.items():
        blob = f"{name} {t['claim']} {t['verdict']} {t['detail']}".lower()
        if needle in blob:
            hits.append(f"[证词] {name}：{t['claim']}（核查：{t['detail']}）")

    return hits


def key_evidence_found(notebook):
    """决定性证据（机房 PIN 记录）是否已经进了笔记本。"""
    return any("0104" in line for line in notebook)


def is_solved(accused, notebook):
    """是否真正破案：指认对了人 + 拿出了决定性证据。用来解锁第二关。"""
    return accused == world.CASE["culprit"] and key_evidence_found(notebook)


def judge(accused, notebook):
    """胜负判定。全部由 Python 决定，不经过 LLM。"""
    culprit = world.CASE["culprit"]
    has_key_evidence = key_evidence_found(notebook)

    if accused != culprit:
        return (
            f"\n【结局 · 失败】\n"
            f"你指认了 {accused}，但真凶是 {culprit}。\n"
            f"线索从一开始就指向机房内部，可惜你抓错了人。\n"
        )
    if not has_key_evidence:
        return (
            f"\n【结局 · 证据不足】\n"
            f"你指认对了 {culprit}，但你拿不出决定性证据（机房 PIN 记录）。\n"
            f"指控被当场驳回，{culprit} 暂时逃脱。\n"
        )
    return (
        f"\n【结局 · 真相大白】\n"
        f"你指认了 {culprit}，并亮出决定性证据：\n"
        f"02:05 进入服务器机房的刷卡记录附带 PIN 0104 —— 正是 {culprit} 工卡 D-104 的末四位。\n"
        f"{culprit} 的心理防线彻底崩溃，交代了全部事实。案件告破。\n"
    )


# ==================================================================
# 盘问：Agent 层
# ==================================================================
def view_profile(name, notebook):
    """查看某人的档案，并把档案记进笔记本。返回这一行。"""
    person = world.PEOPLE[name]
    line = (
        f"[档案] {name}：{person['role']}；工卡 {person['card']}；"
        f"{person['email']}。{person.get('note', '')}"
    )
    if line not in notebook:
        notebook.append(line)
    return line


def talk(npc_name, notebook):
    """和某个 NPC 进行多轮自由盘问。"""
    messages = [{"role": "system", "content": npc.build_npc_prompt(npc_name)}]
    print(f"\n（开始盘问 {npc_name}。输入 /back 结束盘问）\n")
    notebook_text = "\n".join(notebook)

    while True:
        try:
            question = input("你> ").strip()
        except EOFError:
            return
        if question in ("/back", "/quit"):
            return
        if not question:
            continue

        messages.append({"role": "user", "content": question})

        # 确定性层：只有笔记本里真有这条证据，出示才有效
        hits, gated = npc.check_pressure(npc_name, question, notebook_text)
        if gated:
            print(f"  （你只是猜测，没有证据支撑，{npc_name} 不为所动）")
        for point in hits:
            print(f"  （你出示了证据：{point['id']}）")
            messages.append({"role": "system", "content": point["reaction"]})

        try:
            reply = llm.call_llm(messages)["message"].content
        except RuntimeError as e:
            print(f"[错误] {e}")
            continue

        messages.append({"role": "assistant", "content": reply})
        print(f"{npc_name}> {reply}\n")


# ==================================================================
# 主循环
# ==================================================================
def print_help():
    print(
        "\n命令：\n"
        "  /suspects              列出嫌疑人\n"
        "  /investigate <关键词>   搜索线索（门禁 / 服务器 / 物证 / 聊天 / 证词）\n"
        "  /profile <名字>        查看某人的档案（会记进笔记本）\n"
        "  /talk <名字>           盘问某位嫌疑人（/back 结束盘问）\n"
        "  /notebook              查看已收集的线索\n"
        "  /accuse <名字>         指认凶手（游戏结束）\n"
        "  /quit                  退出\n"
    )


def main():
    llm.load_env()

    print("=" * 64)
    print(f"  {world.CASE['title']}")
    print("=" * 64)
    print(world.CASE["summary"])
    print(f"案发时间：{world.CASE['time']}")
    print("\n嫌疑人：Alex（研发）／Bob（前员工）／Carol（外包运维）／David（机房管理员）")
    print("\n你是侦探。找出真凶，并拿出决定性证据。输入 /help 查看命令。")

    notebook = []   # 确定性层：玩家已掌握的线索

    while True:
        try:
            command = input("\n> ").strip()
        except EOFError:
            break

        if not command:
            continue

        if command == "/quit":
            print("游戏结束。")
            break

        if command == "/help":
            print_help()

        elif command == "/suspects":
            for name, person in world.PEOPLE.items():
                print(f"  {name}：{person['role']}")

        elif command == "/notebook":
            if not notebook:
                print("（笔记本还是空的，用 /investigate 去搜线索）")
            else:
                print("【玩家笔记本】")
                for line in notebook:
                    print(f"  - {line}")

        elif command.startswith("/investigate "):
            keyword = command[len("/investigate "):].strip()
            hits = investigate(keyword)
            if not hits:
                print(f"没有找到与 {keyword!r} 相关的线索。")
            else:
                for line in hits:
                    print(f"  + {line}")
                    if line not in notebook:
                        notebook.append(line)

        elif command.startswith("/profile "):
            raw = command[len("/profile "):].strip()
            name = resolve_name(raw, world.PEOPLE)
            if name is None:
                print(f"没有叫 {raw!r} 的嫌疑人。")
            else:
                print("  " + view_profile(name, notebook))

        elif command.startswith("/talk "):
            raw = command[len("/talk "):].strip()
            name = resolve_name(raw, npc.NPCS)
            if name is None:
                print(f"没有叫 {raw!r} 的嫌疑人。")
            else:
                talk(name, notebook)

        elif command.startswith("/accuse "):
            raw = command[len("/accuse "):].strip()
            name = resolve_name(raw, world.PEOPLE)
            if name is None:
                print(f"没有叫 {raw!r} 的嫌疑人。")
            else:
                print(judge(name, notebook))
                break

        else:
            print("未知命令。输入 /help 查看可用命令。")


if __name__ == "__main__":
    main()
