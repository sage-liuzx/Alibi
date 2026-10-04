#!/usr/bin/env bash
#
# 把本地游戏通过 Cloudflare 免费隧道分享到公网。
# 不用注册、不用服务器、不用固定 IP。
#
# 用法：
#     ./share.sh          # 默认转发 8000 端口
#     ./share.sh 9000     # 指定端口
#
# 注意：地址每次启动都会变；隧道只在本机进程存活时有效。

set -e

PORT="${1:-${GAME_PORT:-8000}}"
CF_BIN="${CF_BIN:-/tmp/cloudflared}"

if [ ! -x "$CF_BIN" ]; then
    echo "正在下载 cloudflared…"
    curl -fsSL -o "$CF_BIN" \
        https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x "$CF_BIN"
fi

if ! (ss -tln 2>/dev/null || netstat -tln 2>/dev/null) | grep -q ":${PORT} "; then
    echo "⚠️  端口 ${PORT} 上没有服务在监听。"
    echo "    请先在另一个终端运行：python3 server.py"
    echo
fi

echo "正在建立隧道，几秒后会打印一个 https://xxx.trycloudflare.com 地址…"
echo "把这个地址发给别人，他们就能直接玩。"
echo

exec "$CF_BIN" tunnel --url "http://localhost:${PORT}" --no-autoupdate
