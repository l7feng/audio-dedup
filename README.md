# audio-dedup

音效库重复音频识别工具。独立软件，不并入 SFX Tools。项目记录：知识库 `4-项目-P/92-音频重复识别工具/`。

## 当前状态

- 版本：见 `VERSION`（0.1.0，阶段二已交付 L3，GUI 在阶段三）。
- 判定分层：L1 字节级（大小分组 + SHA256）；L2 音频级（FFmpeg 解码 48kHz 单声道 PCM 样本哈希 + 时长容差）；L3 感知近似（频带能量差指纹，高/中/低疑似分级，只报告不处置）。
- 扫描目标：`E:\音效库-New`，全程只读。无永久删除路径；隔离处置在阶段三，须人类逐次确认。

## 怎么跑

```powershell
.\build.ps1 setup   # 建 .venv、pip install -e .[dev]、写 requirements.lock
.\build.ps1 test    # ruff + pytest
.\.venv\Scripts\python -m audio_dedup.cli scan --root E:\音效库-New --workdir <索引与报告目录>
.\.venv\Scripts\python -m audio_dedup.cli l3 --workdir <同上>        # L3 感知疑似（只读）
.\.venv\Scripts\python -m audio_dedup.cli report --workdir <同上>   # 从索引重写报告
```

`scan` 选项：`--skip-l2`（只做 L1）、`--tolerance`（L2 时长预筛容差秒，默认 0.5）、`--ffmpeg/--ffprobe`。`l3` 选项：`--threshold`（疑似 BER 上限，默认 0.35）、`--workers`（解码线程，默认 4）。复扫同一 workdir 增量复用未变化文件，坏文件按 mtime+size 进黑名单跳过。

## 怎么验

- `pytest`：合成样本矩阵（复制件 / WAV↔FLAC / 仅元数据不同 / 同时长无关文件）检出与零误报。
- 真实库只读报告：分组结果 + 源文件 SHA256 前后一致。

## 已知边界

- CLI 已交付 L1（字节级）、L2（解码 PCM 哈希）、L3（感知疑似分级）；GUI 与隔离处置在阶段三。
- L3 已知边界：纯谐波素材召回弱、拉伸容忍约 ±3%、近静音不判；详见知识库项目 92《01-L3指纹选型实测》。
- FFmpeg 为外部依赖（本机 9.0.1，见 `env.md`），不随仓分发；L2 缺失时显式报错退出。运行时依赖 numpy。
- 压缩包（rar/zip）内的音频不在扫描范围；视频容器（mp4/webm）不算音频。
- 本地仓，无远端；未建 GitHub 发布。LICENSE 未设（非公开仓）。

## 元文件

`CHANGELOG.md` 历史；`VERSION` 与 git tag 一致；`env.md` 运行时与重建；`STRUCTURE.md` 仓内落点契约；`docs/adr/` 决策。