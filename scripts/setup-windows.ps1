$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "需要先安装 Node.js 22 或更高版本：https://nodejs.org/"
}

$NodeMajor = [int]((& node --version).TrimStart("v").Split(".")[0])
if ($NodeMajor -lt 22) {
  throw "当前 Node.js 版本过低，需要 Node.js 22 或更高版本"
}

if (Get-Command py -ErrorAction SilentlyContinue) {
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py -3 -m venv .venv
  }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & python -m venv .venv
  }
} else {
  throw "需要先安装 Python 3.11 或更高版本：https://www.python.org/downloads/windows/"
}

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
& $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else '需要 Python 3.11 或更高版本')"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r server\requirements.txt

if (Get-Command pnpm -ErrorAction SilentlyContinue) {
  & pnpm install --frozen-lockfile
  & pnpm build
} elseif (Get-Command corepack -ErrorAction SilentlyContinue) {
  & corepack pnpm install --frozen-lockfile
  & corepack pnpm build
} else {
  throw "需要安装 Node.js 22 或更高版本"
}

Write-Host ""
Write-Host "安装完成。以后双击 启动明琰AI平台-Windows.cmd 即可运行。" -ForegroundColor Green
