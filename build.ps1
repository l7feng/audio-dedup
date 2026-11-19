param(
    [ValidateSet('setup', 'test', 'gui', 'package')]
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

if ($Action -eq 'gui') {
    & $Py -m audio_dedup.gui
    exit $LASTEXITCODE
}

if ($Action -eq 'package') {
    if (-not (Test-Path $Py)) { throw 'missing .venv, run: .\build.ps1 setup' }
    $Root = $PSScriptRoot
    $Icon = Join-Path $Root 'src\audio_dedup\gui\assets\app.ico'
    if (-not (Test-Path $Icon)) { throw "missing icon: $Icon" }
    # --specpath 会改变相对路径基准，数据文件与入口一律用绝对路径
    $Data = "$(Join-Path $Root 'src\audio_dedup\gui\assets');audio_dedup\gui\assets"
    $Entry = Join-Path $Root 'scripts\gui-entry.py'
    $Dist = Join-Path $Root 'build\dist'
    $Work = Join-Path $Root 'build\pyinstaller'
    # PyInstaller 把日志写到 stderr，PS 5.1 会当成错误记录；这段临时放宽策略，只认退出码
    $SavedPolicy = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Py -m PyInstaller --noconfirm --clean --windowed `
        --name audio-dedup-gui `
        --icon $Icon `
        --add-data $Data `
        --distpath $Dist --workpath $Work --specpath (Join-Path $Root 'build') `
        $Entry
    $Code = $LASTEXITCODE
    $ErrorActionPreference = $SavedPolicy
    if ($Code -ne 0) { throw "pyinstaller failed (exit $Code)" }
    $Exe = Join-Path $Dist 'audio-dedup-gui\audio-dedup-gui.exe'
    if (-not (Test-Path $Exe)) { throw "missing exe: $Exe" }
    $Size = (Get-Item $Exe).Length
    $Count = (Get-ChildItem (Join-Path $Dist 'audio-dedup-gui') -Recurse -File | Measure-Object).Count
    Write-Host "package done: $Exe  ($Size bytes, $Count files)"
    exit 0
}

if (-not (Test-Path $Py)) { throw 'missing .venv, run: .\build.ps1 setup' }
& $Py -m ruff check src tests
if ($LASTEXITCODE -ne 0) { throw 'ruff failed' }
& $Py -m pytest
if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
Write-Host 'test done'