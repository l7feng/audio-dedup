param(
    [ValidateSet('setup', 'test')]
    [string]$Action = 'test'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if ($Action -eq 'setup') {
    if (-not (Test-Path $Py)) { python -m venv .venv }
    & $Py -m pip install -e .[dev]
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    & $Py -m pip freeze --exclude-editable | Set-Content -Encoding ascii requirements.lock
    Write-Host 'setup done'
    exit 0
}

if (-not (Test-Path $Py)) { throw 'missing .venv, run: .\build.ps1 setup' }
& $Py -m ruff check src tests scripts
if ($LASTEXITCODE -ne 0) { throw 'ruff failed' }
& $Py -m pytest
if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
Write-Host 'test done'