#!/usr/bin/env bash
# 等待 Render 部署完成：轮询 /version，直到线上运行的提交 == 指定提交。
#
# 用法：
#   scripts/wait_for_deploy.sh            # 等待当前 HEAD 上线
#   scripts/wait_for_deploy.sh a7e4c54    # 等待指定提交上线
# 环境变量：
#   DEPLOY_URL   测试环境地址（默认见下）
#   TIMEOUT      最长等待秒数（默认 600）
#
# 退出码：0 = 已上线；1 = 超时；2 = 参数或环境错误
set -euo pipefail

URL="${DEPLOY_URL:-https://my-python-app-m3qj.onrender.com}"
TIMEOUT="${TIMEOUT:-600}"
WANT="${1:-$(git rev-parse --short=7 HEAD)}"
WANT="${WANT:0:7}"

if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] && [ $# -eq 0 ]; then
  echo "提示：工作区有未提交的改动，它们不会被部署。"
fi
if ! git branch -r --contains "$WANT" 2>/dev/null | grep -q "origin/main"; then
  echo "错误：提交 ${WANT} 还没有推送到 origin/main，Render 不会部署它。先运行 git push origin main。" >&2
  exit 2
fi

echo "等待 ${WANT} 部署到 ${URL}（最长 ${TIMEOUT}s）..."
start=$(date +%s)
last=""
while true; do
  elapsed=$(( $(date +%s) - start ))
  body=$(curl -s -m 15 "$URL/version" || true)
  live=$(printf '%s' "$body" | sed -n 's/.*"commit":"\([^"]*\)".*/\1/p')
  if [ "$live" = "$WANT" ]; then
    echo "[${elapsed}s] ✅ 已上线：$body"
    health=$(curl -s -m 15 "$URL/health" || true)
    echo "health: $health"
    case "$body" in *'"db":"postgresql"'*) ;; *) echo "⚠️ 线上没有使用 PostgreSQL，请检查 DATABASE_URL" ;; esac
    exit 0
  fi
  if [ "$live" != "$last" ]; then
    echo "[${elapsed}s] 线上版本：${live:-（无响应，可能正在重启）}"
    last="$live"
  fi
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    echo "[${elapsed}s] ❌ 超时：线上仍是 ${live:-无响应}。请到 Render 的 Events/Logs 页面查看部署是否失败。" >&2
    exit 1
  fi
  sleep 15
done
