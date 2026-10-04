"""Phase 11 试验：让大模型扮演玩家来盘问 NPC，验证可玩性。

流程：
    ① 确定性层把"玩家笔记本"（已掌握的证据）交给玩家
    ② 侦探(LLM) --提问--> NPC(LLM, David)
       玩家提到关键证据 → 确定性层给 NPC 注入"被戳穿"状态
       NPC(LLM) --回答--> 侦探(LLM)
    ③ 裁判(LLM) 评估可玩性
"""

import llm
import npc
import world

CASE_BRIEF = """【案件简报】
星核科技（NovaTech）核心项目 Helios 的数据库服务器于 6月12日凌晨遭入侵，
一份含客户身份数据的加密包被盗。
嫌疑人共 4 人：Alex、Bob、Carol、David。"""


def build_notebook():
    """确定性层：把玩家已掌握的证据整理成笔记本。"""
    lines = ["【玩家笔记本 · 已掌握的证据】"]
    for row in world.ACCESS_LOG:
        note = f"（{row['note']}）" if row["note"] else ""
        lines.append(f"- 门禁：{row['time']} 卡号 {row['card']} → {row['door']}{note}")
    return "\n".join(lines)


PLAYER_SYSTEM_TAIL = """
你的目标：拿出笔记本里的证据，当面质问 David，戳穿他的谎言。
规则：
- 一次只问一个问题。
- 尽量直接引用证据，例如『02:05 进机房用的 PIN 0104，是你的工号尾号吧？』
- 不要自己长篇分析，也不要直接宣布结论。"""

NPC_NAME = "David"
TURNS = 8


def main():
    llm.load_env()

    notebook = build_notebook()
    print(notebook, "\n")

    npc_messages = [{"role": "system", "content": npc.build_npc_prompt(NPC_NAME)}]
    player_system = (
        "你是一名侦探，正在盘问嫌疑人 David。\n\n"
        + CASE_BRIEF
        + "\n\n"
        + notebook
        + "\n"
        + PLAYER_SYSTEM_TAIL
    )
    player_messages = [
        {"role": "system", "content": player_system},
        {"role": "user", "content": "你走进审讯室，David 坐在对面。开始你的提问。"},
    ]

    print(f"===== 自对弈开始：侦探(LLM) vs NPC({NPC_NAME}) =====\n")
    pairs = []
    for _ in range(TURNS):
        # 侦探提问
        question = llm.call_llm(player_messages)["message"].content
        player_messages.append({"role": "assistant", "content": question})
        npc_messages.append({"role": "user", "content": question})
        print(f"【侦探】{question}\n")

        # 确定性层：玩家是否出示了关键证据？
        hits = npc.check_pressure(NPC_NAME, question)
        for point in hits:
            print(f"  >>> [出示证据命中：{point['id']}] <<<\n")
            npc_messages.append({"role": "system", "content": point["reaction"]})

        # NPC 回答（仍然不给任何工具）
        answer = llm.call_llm(npc_messages)["message"].content
        npc_messages.append({"role": "assistant", "content": answer})
        player_messages.append({"role": "user", "content": answer})
        print(f"【David】{answer}\n")

        pairs.append((question, answer))

    # 裁判评估
    transcript = "\n".join(f"侦探：{q}\nDavid：{a}" for q, a in pairs)
    truth = "".join(f"- {s}\n" for s in npc.NPCS[NPC_NAME]["secrets"])
    judge_prompt = (
        "下面是一段侦探盘问嫌疑人 David 的对话记录。\n"
        "已知真相（David 确实做到的事）：\n" + truth + "\n"
        "请评估三点，每点用一两句话：\n"
        "1) David 是否始终保持角色、没有跳戏？\n"
        "2) David 是否过早泄露了核心秘密（没被逼问就自己说出来）？\n"
        "3) 面对证据时，David 的反应是否合理（动摇、矛盾、但仍不直接认罪）？\n\n"
        "注意：你只做评估，不要续写或模拟新的对话轮次。\n\n"
        "对话记录：\n" + transcript
    )
    print("===== 裁判评估 =====\n")
    print(llm.call_llm([{"role": "user", "content": judge_prompt}])["message"].content)


if __name__ == "__main__":
    main()
