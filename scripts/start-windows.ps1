$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
  throw "请先双击 安装依赖-Windows.cmd"
}

$env:MINGYAN_DATA_DIR = if ($env:MINGYAN_DATA_DIR) { $env:MINGYAN_DATA_DIR } else { Join-Path $HOME ".mingyan-ai" }
Set-Location $ProjectDir

$Backend = Start-Process -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8000" -PassThru -NoNewWindow
if (Get-Command pnpm -ErrorAction SilentlyContinue) {
  $Web = Start-Process -FilePath "pnpm.cmd" -ArgumentList "dev:web" -PassThru -NoNewWindow
} elseif (Get-Command corepack -ErrorAction SilentlyContinue) {
  $Web = Start-Process -FilePath "corepack.cmd" -ArgumentList "pnpm", "dev:web" -PassThru -NoNewWindow
} else {
  Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
  throw "需要安装 Node.js 22 或更高版本"
}

try {
  for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    try {
      $WebStatus = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:4173/" -TimeoutSec 1
      $ApiStatus = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:4173/api/health" -TimeoutSec 1
      if ($WebStatus.StatusCode -eq 200 -and $ApiStatus.StatusCode -eq 200) {
        Start-Process "http://127.0.0.1:4173/"
        Wait-Process -Id $Web.Id
        exit 0
      }
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  throw "明琰AI平台启动失败，请检查终端日志。"
} finally {
  Stop-Process -Id $Backend.Id, $Web.Id -Force -ErrorAction SilentlyContinue
}
