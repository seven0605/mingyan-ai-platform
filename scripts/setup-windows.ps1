$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 -m venv .venv
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  & python -m venv .venv
} else {
  throw "需要安装 Python 3.11 或更高版本"
}

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else '需要 Python 3.11 或更高版本')"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r server\requirements-dev.txt

if (Get-Command pnpm -ErrorAction SilentlyContinue) {
  & pnpm install
} elseif (Get-Command corepack -ErrorAction SilentlyContinue) {
  & corepack pnpm install
} else {
  throw "需要安装 Node.js 22 或更高版本"
}
Write-Host "依赖安装完成。双击 启动明琰AI平台-Windows.cmd 即可运行。"
