# audio-dedup

音效库重复音频识别工具。独立软件，不并入 SFX Tools。项目记录：知识库 `4-项目-P/92-音频重复识别工具/`。

## 当前状态

- 版本：见 `VERSION`（0.1.0；阶段三 GUI 与流式边导出已落地，未发版，见 `CHANGELOG.md` 的 Unreleased）。
- 判定分层：L1 字节级（大小分组 + SHA256）；L2 音频级（FFmpeg 解码 48kHz 单声道 PCM 样本哈希 + 时长容差）；L3 感知近似（频带能量差指纹，高/中/低疑似分级，只报告不处置）。
- 扫描目标：`E:\音效库-New`，全程只读。无永久删除路径；隔离处置在阶段三，须人类逐次确认。

## 怎么跑

```powershell
.\build.ps1 setup   # 建 .venv、pip install -e .[dev]、写 requirements.lock
.\build.ps1 test    # ruff + pytest
.\.venv\Scripts\python -m audio_dedup.cli scan --root E:\音效库-New --workdir <索引与报告目录>
.\.venv\Scripts\python -m audio_dedup.cli l3 --workdir <同上>        # L3 感知疑似（只读）
.\.venv\Scripts\python -m audio_dedup.cli report --workdir <同上>   # 从索引重写报告
.\.venv\Scripts\python -m audio_dedup.cli export --workdir <同上>   # 只导出 GUI 数据包（不重算）
.\scripts\run-gui.ps1                                             # 桌面 GUI（等价于 -m audio_dedup.gui）
```

`scan` 选项：`--skip-l2`（只做 L1）、`--tolerance`（L2 时长预筛容差秒，默认 0.5）、`--ffmpeg/--ffprobe`。`l3` 选项：`--threshold`（疑似 BER 上限，默认 0.35）、`--workers`（解码线程，默认 4）、`--reset-edges`（清空已导出的边再重建；默认增量续跑）。复扫同一 workdir 增量复用未变化文件，坏文件按 mtime+size 进黑名单跳过。

## GUI 页面

`python -m audio_dedup.gui`（或 `audio-dedup-gui`）打开桌面窗口：分组浏览（L1/L2/L3＋等级＋搜索）、组内文件表与隔离勾选、最多 5 轨波形对比、内嵌试听（不可用时回退系统播放器）、报告导出、后台扫描／L3 任务日志、人类逐次确认后移入隔离区与按批次恢复。

三种处置粒度：

| 粒度 | 入口 | 作用范围 |
|---|---|---|
| 单文件 | 组内文件表「隔离」列勾选 → 移入隔离区 | 只处理当前组里勾中的行 |
| 单文件试听 | 文件表首列 `▶` | 该行独立试听，与当前选中行无关 |
| 整组 / 多组 | 分组列表多选（Ctrl/Shift，或「全选」）→ 批量隔离选中组 | 所选组内全部非保留项 |
| 整个文件夹 | 左下目录树选目录 → 该目录下批量隔离 | 该目录含子目录下所有组的非保留项 |

波形区与文件表一一对应：组内几个文件就几条轨道（最多 60 条，超出滚动）。选文件行会高亮并滚到对应轨道；点轨道标签即选中该文件，点波形区从该位置定位，双击从该位置试听。波形是真实峰值镜像包络，不是合成图形。

视觉口径：深灰阶工作台＋单一暖金强调，只有「需要人注意」的东西上色（L3 疑似、预计可释放、当前活跃轨）。

隔离统一走一个确认弹窗：完整路径清单＋隔离目录可改；单次 ≥50 个文件时，必须勾选「我已逐条核对」才能点确认。

数据源唯一为 workdir 下的 `groups.json`：由 `core/export.py` 生成，含三层分组、文件元数据、L3 相似边与疑似分级；`edges.csv` 是同一份边的可读清单。L3 分组完全从已导出的边重建，GUI 不重算指纹、不碰源音频。隔离＝同盘 rename＋manifest，恢复前逐个核验 SHA256；界面不提供任何永久删除路径。设计见 `docs/adr/0002-流式边导出与GUI数据契约.md`。

打包：`.\build.ps1 package` 产出 `build/dist/audio-dedup-gui/audio-dedup-gui.exe`（onedir，含图标与 `assets/`；同一 exe 加 `--cli` 即分发 CLI 子命令）。

## 怎么验

- `pytest`：合成样本矩阵（复制件 / WAV↔FLAC / 仅元数据不同 / 同时长无关文件）检出与零误报。
- 真实库只读报告：分组结果 + 源文件 SHA256 前后一致。

## 已知边界

- CLI 与 GUI 均已交付 L1（字节级）、L2（解码 PCM 哈希）、L3（感知疑似分级）；真实库 L3 全库尚未跑通（当前索引边数为 0），L3 组待人工听审。
- L3 已知边界：纯谐波素材召回弱、拉伸容忍约 ±3%、近静音不判；详见知识库项目 92《01-L3指纹选型实测》。
- FFmpeg 为外部依赖（本机 9.0.1，见 `env.md`），不随仓分发；L2 缺失时显式报错退出。运行时依赖 numpy，GUI 另需 PySide6（`pip install -e .[gui]`），打包工具为 PyInstaller（`[dev]`）。
- 压缩包（rar/zip）内的音频不在扫描范围；视频容器（mp4/webm）不算音频。
- 本地仓，无远端；未建 GitHub 发布。LICENSE 未设（非公开仓）。

## 元文件

`CHANGELOG.md` 历史；`VERSION` 与 git tag 一致；`env.md` 运行时与重建；`STRUCTURE.md` 仓内落点契约；`docs/adr/` 决策。