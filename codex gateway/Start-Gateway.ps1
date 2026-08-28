param(
    [int]$Port = 4000
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

function Stop-WithMessage([string]$message) {
    Write-Host $message -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $python)) {
    $bootstrap = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $bootstrap) { $bootstrap = Get-Command python.exe -ErrorAction SilentlyContinue }
    if (-not $bootstrap) { Stop-WithMessage 'Python was not found. Install Python 3.11 or newer, then run this script again.' }
    Write-Host 'Creating the virtual environment...'
    & $bootstrap.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage 'Could not create the virtual environment.' }
    Write-Host 'Installing gateway dependencies...'
    & $python -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage 'Could not install gateway dependencies.' }
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env')) -or -not (Test-Path -LiteralPath (Join-Path $projectRoot 'providers.yaml'))) {
    Stop-WithMessage 'Create .env and providers.yaml before starting the gateway.'
}

Start-Process "http://127.0.0.1:$Port/admin/ui"
& $python -m uvicorn app.main:create_app --factory --env-file (Join-Path $projectRoot '.env') --host 127.0.0.1 --port $Port
