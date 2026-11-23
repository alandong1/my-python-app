#!/usr/bin/env bash
# 等待 PR 合并并部署上线：
#   1. 等当前分支的提交（HEAD）被合并进 origin/main（PR 自动合并或负责人手动合并）
#   2. 轮询 /version，直到线上运行的提交 == 合并后的 origin/main
#
# 用法：
#   scripts/wait_for_deploy.sh            # 等待当前 HEAD 合并进 main 并上线
#   scripts/wait_for_deploy.sh a7e4c54    # 等待指定提交（必须已在 main 上）上线
# 环境变量：
#   DEPLOY_URL   测试环境地址（默认读取 deploy.conf）
#   TIMEOUT      最长等待秒数（默认 600）
#
# 退出码：0 = 已上线；1 = 超时；2 = 参数或环境错误
set -euo pipefail

# 无论从哪个目录运行，都切换到仓库根目录（git 命令和 deploy.conf 都依赖它）
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 地址优先取环境变量 DEPLOY_URL，否则读仓库根目录的 deploy.conf
if [ -z "${DEPLOY_URL:-}" ] && [ -f "$ROOT/deploy.conf" ]; then
  DEPLOY_URL="$(sed -n 's/^DEPLOY_URL=//p' "$ROOT/deploy.conf" | tail -1)"
fi
URL="${DEPLOY_URL:-}"
if [ -z "$URL" ]; then
  echo "错误：没有找到测试环境地址。请在 deploy.conf 里设置 DEPLOY_URL。" >&2
  exit 2
fi
TIMEOUT="${TIMEOUT:-600}"
start=$(date +%s)

if [ $# -ge 1 ]; then
  git fetch -q origin main
  WANT="${1:0:7}"
  if ! git merge-base --is-ancestor "$WANT" origin/main 2>/dev/null; then
    echo "错误：提交 ${WANT} 不在 origin/main 上，Render 不会部署它。" >&2
    exit 2
  fi
else
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "提示：工作区有未提交的改动，它们不会被部署。"
  fi
  HEAD_SHA="$(git rev-parse HEAD)"
  # 等 PR 合并：HEAD 成为 origin/main 的祖先，就说明已经合并进去了
  # （所以合并 PR 时要用 merge commit，不能用 squash）
  waited=0
  until git fetch -q origin main && git merge-base --is-ancestor "$HEAD_SHA" origin/main; do
    elapsed=$(( $(date +%s) - start ))
    if [ "$waited" -eq 0 ]; then
      echo "等待 ${HEAD_SHA:0:7} 合并进 main（PR 还没合并：检查测试是否通过，别人的 PR 要负责人 approve）..."
      waited=1
    fi
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
      echo "[${elapsed}s] ❌ 超时：${HEAD_SHA:0:7} 还没有合并进 main。请到 GitHub 上查看 PR 的状态。" >&2
      exit 1
    fi
    sleep 15
  done
  # 合并后 main 的最新提交（merge commit）才是 Render 部署的版本
  WANT="$(git rev-parse --short=7 origin/main)"
fi

echo "等待 ${WANT} 部署到 ${URL}（最长 ${TIMEOUT}s）..."
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
