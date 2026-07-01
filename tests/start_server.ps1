# 用于启动非 reload 的 FastAPI 本地服务器，供 E2E 测试使用。
# 运行此脚本会自动检测并释放占用的 8001 端口，然后启动稳定的 uvicorn 服务。

Set-Location (Join-Path $PSScriptRoot '..')

$Port = 8001
$Connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1

if ($Connection) {
    $PidToKill = $Connection.OwningProcess
    Write-Host "检测到端口 $Port 已被进程 ID $PidToKill 占用，正在终止该进程以释放端口..." -ForegroundColor Yellow
    Stop-Process -Id $PidToKill -Force
    Start-Sleep -Seconds 2
}

Write-Host "正在启动无 reload 的 FastAPI 服务器（端口: $Port）..." -ForegroundColor Green
uvicorn main:app --port $Port
