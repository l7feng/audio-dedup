import csv
import io
import os
from datetime import datetime

from .dedup import keep_suggestion


def atomic_write(path: str, text: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _fmt_size(n):
    return f"{n / 1e6:.1f} MB"


def _fmt_dur(d):
    return f"{d:.2f}s" if d is not None else "—"


def write_reports(workdir: str, root: str, counts: dict, errors: list,
                  groups_l1: list, groups_l2: list, skipped_l2: bool):
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["group_id", "layer", "keep_suggestion", "path", "size_bytes", "duration_s", "sha256", "pcm_hash"])
    md = [
        "# 音频重复扫描报告",
        "",
        f"- 扫描根：`{root}`",
        f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 文件状态：{counts}",
        f"- L1 字节级重复组：{len(groups_l1)}；L2 音频级重复组：{len(groups_l2)}"
        + ("（本次跳过 L2）" if skipped_l2 else ""),
        f"- 扫描/解码错误：{len(errors)} 条（坏文件黑名单，mtime+size 不变则复扫跳过）",
        "",
        "> L1/L2 为确定重复；保留建议按 无损优先 → 码率优先 → 路径短优先。本报告不移动任何文件。",
        "",
    ]
    gid = 0
    for layer, groups in (("L1", groups_l1), ("L2", groups_l2)):
        if not groups:
            continue
        md.append(f"## {layer} 重复组")
        md.append("")
        for group in sorted(groups, key=lambda g: (-len(g), g[0].path)):
            gid += 1
            keep = keep_suggestion(group)
            md.append(f"### 组 {gid}（{len(group)} 个，建议保留 `{keep.path}`）")
            md.append("")
            md.append("| 文件 | 大小 | 时长 |")
            md.append("| --- | --- | --- |")
            for r in sorted(group, key=lambda r: r.path):
                mark = " ⬅ 建议保留" if r.path == keep.path else ""
                md.append(f"| `{r.path}`{mark} | {_fmt_size(r.size)} | {_fmt_dur(r.duration)} |")
                writer.writerow([gid, layer, int(r.path == keep.path), r.path, r.size,
                                 r.duration if r.duration is not None else "", r.sha256 or "", r.pcm_hash or ""])
            md.append("")
    if errors:
        md.append("## 错误清单")
        md.append("")
        for e in errors[:200]:
            md.append(f"- {e}")
        if len(errors) > 200:
            md.append(f"- …其余 {len(errors) - 200} 条见 CSV 同目录 errors.txt")
        md.append("")
        atomic_write(os.path.join(workdir, "errors.txt"), "\n".join(errors))
    atomic_write(os.path.join(workdir, "report.md"), "\n".join(md))
    atomic_write(os.path.join(workdir, "report.csv"), csv_buf.getvalue())
    return gid