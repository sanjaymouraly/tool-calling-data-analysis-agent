<#
.SYNOPSIS
    Start the backend and the frontend development server on Windows.

.DESCRIPTION
    Creates the Python virtual environment, installs the backend and frontend
    dependencies, generates the synthetic demo datasets and starts both
    development servers.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -BackendPort 9000 -FrontendPort 3000
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

Write-Step 'Creating the Python environment'
if (-not (Test-Path '.venv')) {
    py -3.12 -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
python -m pip install --quiet --upgrade pip
pip install --quiet -r backend\requirements.txt

Write-Step 'Installing the frontend dependencies'
Set-Location "$root\frontend"
if (-not (Test-Path 'node_modules')) {
    npm install
}

Write-Step 'Generating the synthetic demo datasets'
Set-Location "$root\backend"
python -m app.demo.generator "$root\data\demo" | Out-Null

Write-Step "Starting the API on http://localhost:$BackendPort"
$backend = Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port',"$BackendPort",'--reload' -WorkingDirectory "$root\backend" -PassThru

Write-Step "Starting the frontend on http://localhost:$FrontendPort"
$frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--port',"$FrontendPort" -WorkingDirectory "$root\frontend" -PassThru

Write-Host "Ready. Open http://localhost:$FrontendPort" -ForegroundColor Green
Write-Host 'Press Ctrl+C to stop.'

try {
    while ($true) { Start-Sleep -Seconds 5 }
}
finally {
    Stop-Process -Id $backend.Id, $frontend.Id -ErrorAction SilentlyContinue
}
