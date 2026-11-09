# audio-dedup

音效库重复音频识别工具。独立软件，不并入 SFX Tools。项目记录：知识库 `4-项目-P/92-音频重复识别工具/`。

## 当前状态

- 版本：见 `VERSION`（0.1.0，阶段一开发中）。
- 判定分层：L1 字节级（大小分组 + SHA256）；L2 音频级（FFmpeg 解码 48kHz 单声道 PCM 样本哈希 + 时长容差）；L3 感知近似（阶段二选型，疑似分级，只报告不处置）。
- 扫描目标：`E:\音效库-New`，全程只读。无永久删除路径；隔离处置在阶段三，须人类逐次确认。

## 怎么跑

```powershell
.\build.ps1 setup   # 建 .venv、pip install -e .[dev]、写 requirements.lock
.\build.ps1 test    # ruff + pytest
audio-dedup scan --root E:\音效库-New --workdir <索引与报告目录>   # 阶段一交付后可用
```

## 怎么验

- `pytest`：合成样本矩阵（复制件 / WAV↔FLAC / 仅元数据不同 / 同时长无关文件）检出与零误报。
- 真实库只读报告：分组结果 + 源文件 SHA256 前后一致。

## 已知边界

- 阶段一 CLI 开发中，尚未交付可跑命令；L3 未选型；GUI 与隔离处置在阶段三。
- FFmpeg 为外部依赖（本机 9.0.1，见 `env.md`），不随仓分发。
- 本地仓，无远端；未建 GitHub 发布。LICENSE 未设（非公开仓）。

## 元文件

`CHANGELOG.md` 历史；`VERSION` 与 git tag 一致；`env.md` 运行时与重建；`STRUCTURE.md` 仓内落点契约；`docs/adr/` 决策。