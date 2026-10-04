"""Phase 9：调查 Agent 测试（Test B）。"""

import agent
import llm

BRIEFING = """【案件简报】
星核科技（NovaTech）核心项目 Helios 的数据库服务器于 6月12日凌晨遭入侵，
一份含客户身份数据的加密包被盗。
已知 4 名嫌疑人：Alex、Bob、Carol、David。

请调查这起案件，告诉我谁最可疑，以及你的证据。"""


def main():
    llm.load_env()
    answer = agent.run_agent(BRIEFING)
    print("\n=== 最终答案 ===")
    print(answer)


if __name__ == "__main__":
    main()
