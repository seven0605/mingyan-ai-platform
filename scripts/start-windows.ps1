$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$AppUrl = "http://127.0.0.1:8000/"
$HealthUrl = "http://127.0.0.1:8000/api/health"

if (-not (Test-Path $VenvPython)) {
  throw "请先双击 安装依赖-Windows.cmd"
}

if (-not (Test-Path (Join-Path $ProjectDir "dist\index.html"))) {
  throw "网页文件尚未生成，请重新双击 安装依赖-Windows.cmd"
}

try {
  $ExistingHealth = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 1
  if ($ExistingHealth.StatusCode -eq 200) {
    Start-Process $AppUrl
    Write-Host "明琰AI平台已经在运行，已打开浏览器。"
    exit 0
  }
} catch {
  # 本机服务尚未启动，继续执行。
}

$UserProfileDir = [Environment]::GetFolderPath("UserProfile")
$env:MINGYAN_DATA_DIR = if ($env:MINGYAN_DATA_DIR) { $env:MINGYAN_DATA_DIR } else { Join-Path $UserProfileDir ".mingyan-ai" }
Set-Location $ProjectDir

$Backend = Start-Process -FilePath $VenvPython -ArgumentList "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8000" -PassThru -NoNewWindow

try {
  for ($Attempt = 0; $Attempt -lt 80; $Attempt++) {
    try {
      $WebStatus = Invoke-WebRequest -UseBasicParsing -Uri $AppUrl -TimeoutSec 1
      $ApiStatus = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 1
      if ($WebStatus.StatusCode -eq 200 -and $ApiStatus.StatusCode -eq 200) {
        Start-Process $AppUrl
        Write-Host "明琰AI平台运行中。关闭此窗口即可停止本地服务。" -ForegroundColor Green
        Wait-Process -Id $Backend.Id
        exit 0
      }
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  throw "明琰AI平台启动失败，请检查终端日志。"
} finally {
  Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
}
