param(
    [string]$Workdir = "D:/Ai-Files/Repos/audio-dedup/build/scan-20261109",
    [string]$Ffmpeg = "ffmpeg"
)
$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Py = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    throw '缺少 .venv；先运行 .\build.ps1 setup，再执行 pip install -e .[gui]'
}
& $Py -m audio_dedup.gui --workdir $Workdir --ffmpeg $Ffmpeg
