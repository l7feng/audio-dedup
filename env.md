# env

## 运行时版本（2026-11-09 实测）

- Python 3.12.10（`python --version`，系统 PATH）。
- FFmpeg 9.0.1-full / ffprobe 同目录（Gyan.FFmpeg winget 包，PATH 可达）：
  `C:/Users/Administrator/AppData/Local/Microsoft/Winget/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.1-full_build/bin/`
- 运行时第三方 Python 依赖：无（标准库 + FFmpeg 子进程）；dev 依赖 pytest / ruff 由 `requirements.lock` 锁定。

## 重建

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m pip freeze --exclude-editable > requirements.lock
.\build.ps1 test
```

或直接 `.\build.ps1 setup`（同效果）。`.venv/` 不入库、不进同步；FFmpeg 需另行安装（winget `Gyan.FFmpeg`）。