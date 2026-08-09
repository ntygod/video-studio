$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 1) 后端 FastAPI（127.0.0.1:8765）
$python = Join-Path $root ".venv\Scripts\python.exe"
$web = Join-Path $root "web"

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root ".venv")
}

& $python -m pip install -q -r (Join-Path $root "requirements.txt")
$backend = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765") -WorkingDirectory $root -PassThru -WindowStyle Hidden

# 2) 前端 Next.js（http://127.0.0.1:3000）
if (-not (Test-Path (Join-Path $web "node_modules"))) { pnpm --dir $web install --no-frozen-lockfile }
try {
    pnpm --dir $web dev
} finally {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id }
}

