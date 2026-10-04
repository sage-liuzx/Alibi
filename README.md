# Alibi

> **一款 AI 侦探游戏，分两关：先当侦探破案，再当被审的真凶。**

星核科技（NovaTech）的核心数据库在 6 月 12 日凌晨被入侵，一份客户数据包被盗。

- **第一关 · 你是侦探** —— 勘查现场、盘问四名嫌疑人，指认出真凶，并拿出决定性证据。
- **第二关 · 你是真凶** —— 通关第一关后解锁。这次你是 David，真正动手的那个人；
  而审你的侦探是一个 **Agent**，它自己决定问什么、查什么。

两关刻意做成**顺序解锁**：先当侦探，否则第二关会剧透第一关的全部悬念。

`Python` · `零第三方依赖` · `原生前端` · `兼容 OpenAI 协议的任意模型`

---

## 玩法

### 第一关 · 你是侦探

搜索现场、盘问嫌疑人、查阅档案，最后指认凶手。

- 指认**必须拿得出证据** —— 猜对了人却没有决定性证据，一样算输
- 通关条件：指认对真凶 **且** 笔记本里有 **PIN 0104**
- 通关后第二关自动解锁，进度会保留（即使你「重新开始」）

### 第二关 · 你是真凶

你是 **David** —— 机房管理员，真凶。
对面的侦探是一个**真正的 Agent**：它根据你的回答和你的小动作，决定下一步查什么。

```text
你  ：删掉机房刷卡记录，把嫌疑引向 Carol
侦探：查门禁 → 发现 PIN 与你的工卡尾号一致 → 回头逼问你
你  ：……
```

| 机制 | 说明 |
|---|---|
| **准备阶段** | 审讯前有 5 点「远程操作」，可删记录 / 改证词 / 伪造嫁祸 |
| **实时审讯** | 侦探一步步走，随时可能停下来提问；你自由作答，也可以抢着销毁证据 |
| **审计痕迹** | 每次篡改都会留下记录；侦探起疑时能从备份**恢复数据** |
| **胜负条件** | 侦探必须拿到 **PIN 0104** 并把它和你绑定才能定罪，否则你全身而退 |

侦探的调查路径**每一局都不同** —— 同一个掩盖策略，结局可能完全相反。

---

## 快速开始

```bash
git clone https://github.com/sage-liuzx/Alibi.git
cd Alibi

# 配置模型（任何兼容 OpenAI 协议的服务）
cat > .env <<'EOF'
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
EOF

# 启动（零依赖）
python3 server.py
```

打开浏览器：

```text
第一关 · 你是侦探    http://localhost:8000
第二关 · 你是真凶    http://localhost:8000/detective.html   （通关第一关后解锁）
```

> 端口可用环境变量改：`GAME_PORT=9000 python3 server.py`
> 修改任何 Python 文件后需要重启服务。

### 其他入口

```bash
python3 main.py         # 让侦探 Agent 独立跑一遍调查
python3 game.py         # 第一关的命令行版（你是侦探）
python3 playtest.py     # 双模型自对弈：一个扮演侦探，一个扮演嫌疑人
```

---

## 分享给别人玩

游戏跑在本地，用 Cloudflare 的免费隧道就能拿到一个公网地址 ——
不要服务器、不要备案、不要固定 IP。

```bash
./share.sh
# 正在建立隧道…
# 🎉 https://xxxx-xxxx-xxxx.trycloudflare.com
```

把这个地址发给别人，他们打开就能直接玩。

> ⚠️ 三点注意
> - 地址**每次启动都会变**，隧道只在你本机进程活着时有效
> - 访客的每一次审讯都会消耗**你自己的模型 API 额度**
> - 服务没有鉴权，别把地址长期公开挂着
>
> 同一个浏览器一个独立会话，多人同时玩不会互相打扰。

---

## 工作原理

### Agent 循环

`agent.py` 是核心。它做的事情一句话说得完：

```python
for step in range(max_steps):
    result = llm.call_llm(messages, tools=tool_schemas)   # 问模型
    if not message.tool_calls:
        return message.content                            # 不要工具 = 最终答案
    messages.append(assistant_message)                    # 记下它说过什么
    for tool_call in message.tool_calls:                  # 要工具 → 执行
        messages.append({"role": "tool", "content": execute_tool(tool_call)})
    # 带着新上下文再问一遍
```

模型请求工具 → 代码执行 → 结果回填上下文 → 再问模型，直到模型不再要工具。

### 工具的定义方式

每个工具都是三件套（`tools.py`）：

```text
1. Python 函数      —— 真正去查数据
2. Tool Schema      —— 给模型看的说明书
3. 注册进 Registry  —— 完成「名字 → 函数」的映射
```

模型在 `tool_calls` 里只返回一个**名字字符串**和一个 JSON **字符串**参数，
Python 靠名字在 Registry 里找到对应的函数执行。

### 审讯为什么能"暂停"等你打字

普通 Agent 循环是阻塞的，而 Web 是请求/响应。所以 `interrogation.py` 把它拆成了一个显式状态机：

```python
advance(session)        # 让 Agent 走一步，然后停下
    · 查证   → status = "ready"      玩家可以抢着掩盖
    · 提问   → status = "waiting"    玩家必须回答
    · 定案   → status = "finished"

answer(session, text)   # 把玩家的话作为工具结果塞回去，继续推进
```

会话状态保存在 `server.py` 的 `DETECTIVE["session"]` 里，在多个 HTTP 请求之间保持不丢。
这等价于 LangGraph 里的 `interrupt()` + checkpointer。

### 世界是战场

```text
侦探的工具 = 【读】一份世界副本（world.py 的深拷贝）
玩家的操作 = 【改】这份副本（删除 / 篡改 / 伪造）
```

玩家改的是副本，不会污染原始案件数据。每次篡改都会追加一条审计痕迹；
侦探如果发现异常，可以调用恢复工具把数据取回来。

**胜负判定完全由 Python 代码决定，不经过 LLM 自评。**

---

## 目录结构

```text
alibi/
├── llm.py              LLM 调用封装（唯一直接使用 openai SDK 的地方）
├── agent.py            Agent 循环本体
├── tools.py            5 个查询工具（函数 + Schema + Registry）
├── world.py            案件数据（纯数据，无逻辑）
│
├── game.py             第一关的确定性层（搜索 / 判定 / 档案 / 盘问）
├── npc.py              4 名嫌疑人的人设、秘密与被戳穿时的反应
├── playtest.py         双模型自对弈实验
│
├── interrogation.py    第二关：侦探提示词 + 玩家篡改 + 可暂停状态机
├── server.py           Web 后端（标准库 http.server，按 cookie 隔离多会话 + 关卡解锁）
├── share.sh            一键用 Cloudflare 免费隧道把游戏分享到公网
└── web/                前端（原生 HTML / CSS / JS，无构建步骤）
    ├── index.html · game.js · style.css          第一关
    └── detective.html · detective.js             第二关
```

---

## 配置

项目根目录的 `.env`：

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | API 密钥 |
| `OPENAI_BASE_URL` | 兼容 OpenAI 协议的服务地址 |
| `OPENAI_MODEL` | 模型名 |

`.env` 已在 `.gitignore` 中，不会被提交；可参照 `.env.example` 创建。

---

## 已知限制

- **单局内存状态**：重启服务即重置，暂不支持存档。
- **无鉴权**：面向本地游玩的轻量服务，请勿直接暴露到公网。
- **平衡性依赖调参**：第二关的胜负概率由 `MAX_STEPS` / `START_ACTIONS` 决定，目前靠实际对局评估，没有自动化测试。
- **进度存在内存**：第二关的解锁状态跟着会话走，重启服务后所有人都会回到第一关。

---

## 许可

MIT
