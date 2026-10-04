# Alibi

> 从零手写一个纯 Python Mini Agent —— 并把它做成一场「AI 侦探审问真凶」的游戏。

**不依赖任何 Agent 框架**（没有 LangChain、没有 LangGraph）。
Agent 循环、工具调用、人类介入（human-in-the-loop）、会话暂停与恢复，
全部用 Python 标准库 + `openai` SDK 写出来 —— 总共约 2000 行。

做这件事只有一个目的：**搞清楚那些 Agent 框架到底封装了什么。**

---

## 1. 这个项目是什么

它同时是两样东西：

| 身份 | 说明 |
|---|---|
| **教学项目** | 一个可运行的 Agent Loop，每层都手写、可读、可改、可打断点 |
| **一个游戏** | 一起商业窃密案，你可以当侦探，也可以当被审的嫌疑人 |

案件背景（虚构）：星核科技（NovaTech）的核心项目 Helios 数据库在 6 月 12 日凌晨遭入侵，
一份含客户身份数据的加密包被盗。四名嫌疑人：Alex、Bob、Carol、David。

---

## 2. 两种玩法

### 玩法一：你是侦探（经典模式）

打开首页 `http://localhost:8000`。你搜索线索、盘问嫌疑人、最后指认凶手。
嫌疑人由 LLM 扮演 —— 但它们**不是 agent**（原因见第 5 节）。

### 玩法二：AI 是侦探，你是真凶（`/detective.html`）

**这是本项目真正的核心。**

- 你是 David —— 机房管理员，**你确实偷了数据**。
- 对面的侦探是**一个真正的 agent**：它自己决定问什么、查什么、什么时候收网。
- 审讯开始前，你可以偷偷远程操作公司系统，**抹掉指向自己的记录**。

```text
你的目标：在侦探拿到决定性证据（PIN 0104）之前，把水搅浑。
侦探的目标：在审讯结束前，把 0104 和你这个人绑定起来。
```

---

## 3. 快速开始

```bash
# 1) 配置密钥
cd alibi
cat > .env <<'EOF'
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
EOF

# 2) 启动 Web 游戏（零依赖，标准库 http.server）
python3 server.py

# 3) 浏览器打开
#    经典模式        http://localhost:8000
#    AI 侦探模式     http://localhost:8000/detective.html
```

> 端口可用环境变量改：`GAME_PORT=9000 python3 server.py`
> 任何 Python 改动都需要重启服务。

### 命令行模式

```bash
python3 main.py         # 让「侦探 Agent」独立跑一遍调查（测试 Agent Loop）
python3 game.py         # 经典模式的 CLI 版（你是侦探）
python3 playtest.py     # LLM 自对弈：一个 LLM 当侦探，一个 LLM 当 NPC
```

---

## 4. 目录结构

```text
alibi/
├── llm.py              LLM 调用封装（唯一碰 openai SDK 的地方）
├── agent.py            ★ Agent Loop 本体：调用 → 执行工具 → 回填 → 再调用
├── tools.py            5 个查询工具（Python 函数 + Tool Schema + Registry）
├── world.py            案件世界 —— 纯数据，无逻辑
│
├── game.py             经典模式的确定性层（搜索 / 判定 / 档案 / 盘问）
├── npc.py              4 个 NPC 的人设、秘密、被戳穿的反应
├── playtest.py         LLM 自对弈实验（验证 NPC 可玩性）
│
├── interrogation.py    ★ AI 侦探模式：侦探 prompt + 玩家篡改 + 可暂停状态机
├── server.py           Web 后端（http.server，零依赖）
└── web/                前端（原生 HTML/CSS/JS，无框架）
    ├── index.html / game.js / style.css      经典模式
    └── detective.html / detective.js         AI 侦探模式
```

`★` 标记的两个文件是本项目的核心。

---

## 5. 核心原理

### 5.1 Agent Loop 到底是什么

`agent.py` 里全部的秘密就是这一个循环：

```python
for step in range(max_steps):
    result = llm.call_llm(messages, tools=tool_schemas)   # 问模型
    if not message.tool_calls:
        return message.content                            # 不要工具 = 最终答案，收工
    messages.append(assistant_message)                    # 它说过什么要记下来
    for tool_call in message.tool_calls:                  # 要工具 → 执行
        messages.append({"role": "tool", "content": execute_tool(tool_call)})
    # 然后拿新的 messages 再问一遍
```

**没有魔法。** 所谓 Agent，就是「模型请求工具 → 代码执行 → 结果塞回上下文 → 再问模型」，
循环到模型不再要工具为止。

### 5.2 工具 = Python 函数 + Schema

每个工具都是三件套（`tools.py`）：

```text
1. Python 函数        —— 真正去查数据
2. Tool Schema        —— 给 LLM 看的说明书（JSON）
3. 注册进 Registry    —— 完成「名字 → 函数」的映射
```

**`name` 是唯一的连接键。** 模型只在 `tool_calls` 里返回一个名字字符串，
Python 靠这个名字在 Registry 里找到函数。`arguments` 是 JSON **字符串**，不是对象 —— 这是新手最常踩的坑。

### 5.3 什么时候才真正需要 Agent？

判断标准只有一句话：

> **下一步做什么，是不是取决于上一步查到了什么？**

- 如果下一步可以事先写死 → 单次 LLM 调用就够了，**不要用 Agent**。
- 如果路径在运行前未知 → 才需要 Agent。

这就是本项目最反直觉的结论：

```text
NPC（嫌疑人）不需要 Agent
    它唯一要决定的是「这条证据面前，认还是不认」
    → 一次带好上下文的 LLM 调用就是正确答案
    → 给它配工具是「工具表演」（tool theater）

侦探需要 Agent
    它事先不知道要查什么，路径由嫌疑人的回答决定
    → 这才是 Agent 存在的理由
```

### 5.4 人类介入：Agent 怎么「暂停」等你打字

普通 Agent 循环是阻塞的（`input()`）。Web 是请求/响应，塞不进一个阻塞循环。
所以 `interrogation.py` 把它拆成了一个**显式状态机**：

```python
advance(session)        # 让 agent 走一步，然后停下
    · 查证   → status="ready"     玩家可以抢着掩盖
    · 提问   → status="waiting"   玩家必须回答
    · 定案   → status="finished"

answer(session, text)   # 把玩家的回答作为 tool 结果塞回去，再继续
```

**这就是 LangGraph 的 `interrupt()` + checkpointer 的手写版。**
`server.py` 里的 `DETECTIVE["session"]` 就是那个 checkpointer —— 会话状态存在内存里，
请求之间不丢。

### 5.5 与 LangGraph 的对照表

| 手写版（本项目） | LangGraph 里的概念 |
|---|---|
| `messages` 列表 | State |
| `llm.call_llm(...)` | Agent 节点 |
| `execute_tool(tool_call)` | ToolNode |
| `if message.tool_calls` | 条件边 |
| `max_steps` | `recursion_limit` |
| `DETECTIVE["session"]` | Checkpointer |
| `advance()` / `answer()` | `interrupt()` + `resume` |

看完这张表，再去看 LangGraph 的文档，会发现它给的正是这几样东西的**工程化版本**：
持久化、并发、流式输出、可视化、重试。**理解了这个循环，框架就不再是黑箱。**

---

## 6. AI 侦探模式的机制

### 世界是战场

```text
侦探的工具 = 【读】世界（一份深拷贝）
玩家的手段   = 【改】世界（删除 / 篡改 / 伪造）
```

玩家改的是 `fresh_world()` 复制出来的副本，不会污染全局 `world.py`。
每次篡改都会留下一条**审计痕迹**；侦探如果起疑，可以 `recover_deleted_log` 尝试恢复。

### 胜利条件

```text
侦探赢：conclude(guilty=True) 且 evidence 里出现「0104」
玩家赢：其余全部情况
```

也就是说：**侦探必须把 PIN 0104 和 David 这个人绑定起来，才能定罪。**

PIN 0104 藏在 **5 条独立路线**里，玩家有 **5 个行动点**，
但「清除审计」必须占掉 1 点 —— 所以玩家最多只能盖住 4 条，**永远会剩 1 条活口**。
剩哪一条、赌侦探漏看哪一条，是这个模式唯一需要玩家做的判断。

**由于侦探是 LLM，它的调查路径每局都不同 —— 同一个掩盖策略，结局会不一样。**
这正是这个模式想要的效果：不是固定解，而是随机应变。

### 玩家可以做什么

```text
① 删机房刷卡记录          ⑤ 篡改 Carol 的笔录
② 清空 PIN 技术分析        删自己的门禁记录 / 删除借卡聊天
③ 改自己的证词             清空服务器日志 / 伪造嫁祸记录
④ 清空门锁本地缓存         清除审计痕迹
```

---

## 7. 配置

`.env`（**已在 `.gitignore` 中，绝不会提交**）：

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | API 密钥 |
| `OPENAI_BASE_URL` | 兼容 OpenAI 协议的服务地址（如 `https://api.deepseek.com/v1`） |
| `OPENAI_MODEL` | 模型名 |

因为用了兼容 OpenAI 协议的 SDK，**换成任何兼容服务（DeepSeek / 通义 / 本地 vLLM…）都只改这三行。**

---

## 8. 已知限制

- **单局内存状态**：重启服务即重置，还没有存档功能。
- **平衡性靠实测调参**：AI 侦探模式的胜负概率依赖 `MAX_STEPS` / `START_ACTIONS`，
  需要真模型跑多局才能评估，没有自动化测试。
- **无鉴权**：`server.py` 是本地玩的教学服务，不要直接暴露到公网。
- **`main.py` 会打印工具调用日志**：这是刻意保留的教学输出。

---

## 9. 项目名前由来

**Alibi**（不在场证明）。

游戏里你做的每一件事 —— 删门禁记录、改自己的证词、清空门锁缓存、嫁祸 Carol ——
都是在维护同一个东西：**你的不在场证明**。

而 AI 侦探在做的，就是把它一条条拆掉。

技术内核那个「调用工具 → 回填结果 → 再调用」的循环，是这个项目的手段，不是它的名字。
