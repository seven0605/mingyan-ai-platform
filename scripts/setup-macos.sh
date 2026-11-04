#!/bin/zsh
set -e

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
python_bin="${PYTHON_BIN:-$(command -v python3 || true)}"
pnpm_bin="$(command -v pnpm || true)"
corepack_bin="$(command -v corepack || true)"

[[ -n "$python_bin" ]] || { echo "需要安装 Python 3.11 或更高版本"; exit 1; }
[[ -n "$pnpm_bin" || -n "$corepack_bin" ]] || { echo "需要安装 Node.js 22 或更高版本"; exit 1; }

"$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "需要 Python 3.11 或更高版本")'
cd "$project_dir"
"$python_bin" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r server/requirements.txt
if [[ -n "$pnpm_bin" ]]; then
  "$pnpm_bin" install
else
  "$corepack_bin" pnpm install
fi

echo "依赖安装完成。双击“启动明琰AI平台.command”即可运行。"
