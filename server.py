"""Web 版游戏后端（Python 标准库 http.server，零依赖）。

启动：
    python3 server.py
然后浏览器打开 http://localhost:8000 （端口可用 GAME_PORT 环境变量改）

会话：每个浏览器一个独立会话（靠 cookie 里的 sid 区分），多人同时玩互不干扰。
      会话只存在内存里，重启服务即清空。
"""

import json
import os
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import game
import interrogation
import llm
import npc
import world

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORT = int(os.environ.get("GAME_PORT", "8000"))

# 会话表：sid -> 会话状态。超过上限就丢最老的，防止内存无限增长。
MAX_SESSIONS = 500
SESSIONS = OrderedDict()


# ==================================================================
# 会话管理
# ==================================================================
def new_session():
    return {"notebook": [], "conversations": {}, "detective": None}


def reset_session(session):
    session["notebook"] = []
    session["conversations"] = {}
    session["detective"] = None


def get_session(handler):
    """从 cookie 取 sid；没有（或已过期）就新建一个。"""
    sid = handler.get_cookie("sid")
    if sid and sid in SESSIONS:
        SESSIONS.move_to_end(sid)
        return SESSIONS[sid]

    sid = uuid.uuid4().hex
    SESSIONS[sid] = new_session()
    handler.new_sid = sid          # 交给 _send 去写 Set-Cookie
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)
    return SESSIONS[sid]


# ==================================================================
# API 逻辑
# ==================================================================
def api_state(session):
    return {
        "case": {
            "title": world.CASE["title"],
            "summary": world.CASE["summary"],
            "time": world.CASE["time"],
        },
        "suspects": [
            {"name": name, "role": person["role"]}
            for name, person in world.PEOPLE.items()
        ],
        "notebook": session["notebook"],
    }


def api_investigate(session, keyword):
    hits = game.investigate(keyword)
    for line in hits:
        if line not in session["notebook"]:
            session["notebook"].append(line)
    return {"hits": hits, "notebook": session["notebook"]}


def api_talk(session, npc_name, message):
    key = game.resolve_name(npc_name, npc.NPCS)
    if key is None:
        return {"error": f"没有叫 {npc_name!r} 的嫌疑人。"}

    convo = session["conversations"].setdefault(
        key, [{"role": "system", "content": npc.build_npc_prompt(key)}]
    )
    convo.append({"role": "user", "content": message})

    # 确定性层：只有笔记本里真有这条证据，出示才有效
    hits, gated = npc.check_pressure(key, message, "\n".join(session["notebook"]))
    for point in hits:
        convo.append({"role": "system", "content": point["reaction"]})

    try:
        reply = llm.call_llm(convo)["message"].content
    except RuntimeError as e:
        return {"error": str(e)}

    convo.append({"role": "assistant", "content": reply})
    return {"reply": reply, "pressure": [p["id"] for p in hits], "gated": gated}


def api_profile(session, npc_name):
    key = game.resolve_name(npc_name, world.PEOPLE)
    if key is None:
        return {"error": f"没有叫 {npc_name!r} 的嫌疑人。"}
    line = game.view_profile(key, session["notebook"])
    person = world.PEOPLE[key]
    return {
        "profile": {
            "name": key,
            "role": person["role"],
            "card": person["card"],
            "email": person["email"],
            "note": person.get("note", ""),
        },
        "archive": line,
        "notebook": session["notebook"],
    }


def api_accuse(session, npc_name):
    key = game.resolve_name(npc_name, world.PEOPLE)
    if key is None:
        return {"error": f"没有叫 {npc_name!r} 的嫌疑人。"}
    ending = game.judge(key, session["notebook"])
    return {
        "ending": ending,
        "win": key == world.CASE["culprit"],
        "culprit": world.CASE["culprit"],
    }


# ==================================================================
# AI 侦探模式：agent 当侦探，玩家当嫌疑人
# ==================================================================
def _detective_session(session):
    if session["detective"] is None:
        session["detective"] = interrogation.new_session()
    return session["detective"]


def api_detective_start(session):
    session["detective"] = interrogation.new_session()
    return {
        "brief": interrogation.PLAYER_BRIEF,
        "actions": [
            {"id": key, "label": act["label"], "desc": act["desc"]}
            for key, act in interrogation.ACTIONS.items()
        ],
        "snapshot": interrogation.snapshot(session["detective"]),
    }


def api_detective_act(session, action_id):
    return interrogation.do_action(_detective_session(session), action_id)


def api_detective_advance(session):
    return interrogation.advance(_detective_session(session))


def api_detective_answer(session, text):
    return interrogation.answer(_detective_session(session), text)


# ==================================================================
# HTTP 处理
# ==================================================================
CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    new_sid = None

    def get_cookie(self, name):
        raw = self.headers.get("Cookie", "") or ""
        for part in raw.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    def _send(self, code, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        else:
            data = body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if self.new_sid:
            self.send_header("Set-Cookie", f"sid={self.new_sid}; Path=/; SameSite=Lax")
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, filename):
        path = os.path.join(WEB_DIR, filename)
        if not os.path.exists(path):
            self._send(404, {"error": "not found"})
            return
        ext = filename.rsplit(".", 1)[-1]
        with open(path, "rb") as f:
            self._send(200, f.read(), CONTENT_TYPES.get(ext, "text/plain"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file("index.html")
        elif self.path == "/style.css":
            self._serve_file("style.css")
        elif self.path == "/game.js":
            self._serve_file("game.js")
        elif self.path == "/detective.html":
            self._serve_file("detective.html")
        elif self.path == "/detective.js":
            self._serve_file("detective.js")
        elif self.path == "/api/state":
            self._send(200, api_state(get_session(self)))
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
            return

        session = get_session(self)

        if self.path == "/api/investigate":
            self._send(200, api_investigate(session, payload.get("keyword", "")))
        elif self.path == "/api/profile":
            self._send(200, api_profile(session, payload.get("npc", "")))
        elif self.path == "/api/talk":
            self._send(200, api_talk(session, payload.get("npc", ""), payload.get("message", "")))
        elif self.path == "/api/accuse":
            self._send(200, api_accuse(session, payload.get("npc", "")))
        elif self.path == "/api/detective/start":
            self._send(200, api_detective_start(session))
        elif self.path == "/api/detective/act":
            self._send(200, api_detective_act(session, payload.get("action", "")))
        elif self.path == "/api/detective/advance":
            self._send(200, api_detective_advance(session))
        elif self.path == "/api/detective/answer":
            self._send(200, api_detective_answer(session, payload.get("text", "")))
        elif self.path == "/api/reset":
            reset_session(session)
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args):
        pass  # 静音，避免刷屏


def main():
    llm.load_env()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"游戏已启动 → http://localhost:{PORT}")
    print("（Ctrl+C 停止）")
    server.serve_forever()


if __name__ == "__main__":
    main()
