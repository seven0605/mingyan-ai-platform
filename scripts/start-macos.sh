#!/bin/zsh
set -e

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
pnpm_bin="$(command -v pnpm || true)"
corepack_bin="$(command -v corepack || true)"

[[ -x "$project_dir/.venv/bin/python" ]] || { echo "请先双击“安装依赖-macOS.command”"; exit 1; }
[[ -n "$pnpm_bin" || -n "$corepack_bin" ]] || { echo "需要安装 Node.js 22 或更高版本"; exit 1; }

cd "$project_dir"
MINGYAN_DATA_DIR="${MINGYAN_DATA_DIR:-$HOME/.mingyan-ai}" \
  .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 &
backend_pid=$!
if [[ -n "$pnpm_bin" ]]; then
  "$pnpm_bin" dev:web &
else
  "$corepack_bin" pnpm dev:web &
fi
web_pid=$!

cleanup() {
  kill "$backend_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for attempt in {1..40}; do
  if curl --silent --fail --max-time 1 http://127.0.0.1:4173/ >/dev/null && \
    curl --silent --fail --max-time 1 http://127.0.0.1:4173/api/health >/dev/null; then
    open http://127.0.0.1:4173/
    wait "$web_pid"
    exit 0
  fi
  sleep 0.25
done

echo "明琰AI平台启动失败，请检查终端日志。"
exit 1
